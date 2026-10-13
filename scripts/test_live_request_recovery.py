"""Offline request recovery tests. LAYER: Tools; no provider or production capture."""
import argparse,asyncio,json,sys,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'js-development'))
from jarvis_core.serve.hearth import Hearth,HearthConfig
from jarvis_core.serve import live_voice as lv

class Brain:
    async def respond(self,question,session,**kwargs):
        if question=='fail':raise RuntimeError('fixture provider failure')
        if question=='stuck':await asyncio.sleep(20)
        if question=='deep':
            yield {'type':'deep','model':'fixture'}
            return
        yield {'type':'token','text':'Recovered.'}
        yield {'type':'done','answer':'Recovered.','model':'fixture'}

class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events=[]
        self.hearth=Hearth(HearthConfig())
        async def send(message):
            if message.get('text'):self.events.append(json.loads(message['text']))
        self.live=lv.LiveSession(self.hearth,send,brain=Brain(),engine=SimpleNamespace())
        self.live.session='old'
        self.live.ephemeral=True
        self.live.speak=False
        self.live._log=lambda timing:asyncio.sleep(0)

    async def start(self,question):
        await self.live.on_text(json.dumps({'type':'text','question':question}))
        await asyncio.sleep(.015)
        return self.live.turn

    async def test_failed_brain_releases_slot_and_next_turn_answers(self):
        task=await self.start('fail')
        if task:await task
        self.assertFalse(self.hearth._slot.locked())
        self.assertEqual(self.live.state,'listening')
        task=await self.start('hello')
        if task:await task
        self.assertTrue(any(e.get('text')=='Recovered.' and e['type']=='answer' for e in self.events))

    async def test_no_progress_timeout_recovers(self):
        with patch.object(lv,'VOICE_PROGRESS_TIMEOUT_S',.03):
            task=await self.start('stuck')
            if task:await task
        self.assertFalse(self.hearth._slot.locked())
        self.assertTrue(any('stopped responding' in e.get('error','') for e in self.events))

    async def test_new_session_cancels_old_turn_and_answers_new_question(self):
        await self.start('stuck')
        self.assertTrue(self.hearth._slot.locked())
        await self.live.on_text(json.dumps({'type':'config','session':'new'}))
        self.assertFalse(self.hearth._slot.locked())
        self.assertEqual(self.live.session,'new')
        self.assertTrue(any(e['type']=='state' and e['session']=='new' for e in self.events))
        task=await self.start('hello')
        if task:await task
        answers=[e for e in self.events if e['type']=='answer']
        self.assertEqual([e['session'] for e in answers],['new'])

    async def test_stop_cancels_generation_but_mute_does_not(self):
        await self.start('stuck')
        await self.live.on_text(json.dumps({'type':'interrupt','cancel_turn':False}))
        self.assertTrue(self.hearth._slot.locked())
        await self.live.on_text(json.dumps({'type':'interrupt','cancel_turn':True}))
        self.assertFalse(self.hearth._slot.locked())

    async def test_busy_is_visible_error_without_synthesized_robot_line(self):
        await self.hearth._slot.acquire()
        try:
            task=await self.start('hello')
            if task:await task
            self.assertTrue(any(e['type']=='error' for e in self.events))
            self.assertFalse(any(e['type']=='audio_start' for e in self.events))
        finally:self.hearth._slot.release()

    async def test_deep_worker_cleanup_precedes_releasing_slot(self):
        entered=threading.Event();cleaned=threading.Event()
        async def ask(question,**kwargs):
            entered.set()
            try:await asyncio.sleep(20)
            finally:
                await asyncio.sleep(.05)
                cleaned.set()
        self.hearth._ask_fn=ask
        await self.start('deep')
        for _ in range(100):
            if entered.is_set():break
            await asyncio.sleep(.01)
        self.assertTrue(entered.is_set())
        await self.live.on_text(json.dumps({'type':'config','session':'new'}))
        self.assertTrue(cleaned.is_set())
        self.assertFalse(self.hearth._slot.locked())
        task=await self.start('hello')
        if task:await task
        self.assertTrue(any(e['type']=='answer' and e['session']=='new' for e in self.events))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.parse_args()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RecoveryTests))
    raise SystemExit(0 if result.wasSuccessful() else 1)
