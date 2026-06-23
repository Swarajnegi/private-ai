# Data Ingestion & Acquisition — Practice MCQs (7%)

1. A team has two new ingestion requirements. Source 1 is a continuously growing folder of CSV files landing in an S3 bucket; source 2 is a real-time clickstream published to an Apache Kafka topic. They want incremental, exactly-once ingestion into separate Delta tables with minimal custom code. Which approach correctly maps each source to a supported Databricks ingestion mechanism?

   A. Use Auto Loader (`cloudFiles`) for the S3 CSV folder, and Spark Structured Streaming with the `kafka` source for the Kafka topic.
   B. Use Auto Loader (`cloudFiles`) for both sources, setting `cloudFiles.format` to `kafka` for the Kafka topic.
   C. Use `COPY INTO` for the S3 CSV folder, and Auto Loader (`cloudFiles`) for the Kafka topic.
   D. Use Spark Structured Streaming with the `kafka` source for both, pointing the file path option at the S3 bucket for the CSV folder.

2. An engineer reads a folder of scanned PDF documents for a downstream OCR job using Auto Loader: `spark.readStream.format("cloudFiles").option("cloudFiles.format", "binaryFile").load(path)`. Which statement about the resulting DataFrame is correct?

   A. The DataFrame has a fixed schema of `path`, `modificationTime`, `length`, and `content`, where `content` holds the raw file bytes; no OCR or text parsing is performed.
   B. The DataFrame parses each PDF into structured text columns automatically, since `binaryFile` performs document text extraction before loading.
   C. The DataFrame contains only a single `value` string column holding the file path; the bytes must be fetched in a later step.
   D. The schema is inferred per file, so PDFs with different internal structures produce different column sets in the same DataFrame.

3. An engineer must incrementally ingest XML order files from cloud storage, where each `<order>` element should map to one row. They start: `spark.readStream.format("cloudFiles").option("cloudFiles.format", "xml").load(path)`. The stream fails to produce the expected one-row-per-order structure. What is the most likely fix?

   A. Specify the `rowTag` option (e.g., `.option("rowTag", "order")`) so Auto Loader knows which XML element maps to a DataFrame row.
   B. XML is not a supported Auto Loader format; switch to converting the files to JSON before ingestion.
   C. Add `.option("multiLine", "true")`, which is what defines the per-row element boundary for XML.
   D. Set `.option("cloudFiles.format", "text")` and parse the XML manually with a UDF, since `cloudFiles` cannot read XML.

4. A streaming job reads from Kafka and writes to a Delta table that downstream consumers stream from. Requirements: append-only semantics, exactly-once delivery, and the ability to resume after a cluster restart without duplicating or losing records. Which `writeStream` configuration meets all three?

   A. `.writeStream.outputMode("append").option("checkpointLocation", "/path/_checkpoints").toTable("catalog.schema.events")`
   B. `.writeStream.outputMode("complete").toTable("catalog.schema.events")` with no checkpoint, relying on Delta's transaction log for recovery.
   C. `.write.mode("append").saveAsTable("catalog.schema.events")` inside a `foreachBatch` loop with manual offset tracking in a Python list.
   D. `.writeStream.outputMode("update").option("checkpointLocation", "/path/_checkpoints").toTable("catalog.schema.events")`

5. An engineer is incrementally ingesting a folder of files with Auto Loader and wants to avoid defining or maintaining a schema manually while keeping schema-inference cost low. The same logical data is available in two layouts in the landing zone: CSV and Parquet. Which choice and reasoning is correct?

   A. Ingest the Parquet files; Parquet embeds its schema and column types in the file metadata, so Auto Loader reads types directly rather than inferring CSV columns as strings (or sampling).
   B. Ingest the CSV files; CSV is self-describing and carries explicit data types, so no inference is needed.
   C. Either is identical for schema handling, because Auto Loader always requires an explicit `cloudFiles.schemaHints` map regardless of format.
   D. Ingest the CSV files, because Auto Loader cannot infer schema from Parquet and requires a user-supplied schema for all columnar formats.

6. An Auto Loader stream ingesting from cloud storage is healthy at low volume, but the source directory now receives millions of new files per hour and directory-listing latency dominates each micro-batch. The engineer wants Auto Loader to discover new files without repeatedly listing the entire directory. Which configuration addresses this, and what is its scope?

   A. Use file notification mode (e.g., `cloudFiles.useNotifications=true`, or file events on the external location), which subscribes to cloud-storage file events via a notification/queue service and scales to millions of files per hour — and it applies only to cloud object storage sources.
   B. Switch the stream to a Kafka source, since file notification mode is implemented on top of Kafka topics under the hood.
   C. Increase `cloudFiles.maxFilesPerTrigger`; directory listing mode is already the most scalable discovery method and notification mode does not exist.
   D. Set `cloudFiles.backfillInterval` to `0` to disable all directory listing, which is what enables event-based discovery without any notification service.

---

## Answers & Explanations

1. **A** — Auto Loader (`cloudFiles`) ingests incrementally from cloud object storage only (S3, ADLS, GCS, UC volumes, Blob); its `cloudFiles.format` accepts exactly `avro`, `binaryFile`, `csv`, `json`, `orc`, `parquet`, `text`, `xml` — never `kafka`. Message buses are read with Structured Streaming's native `kafka` source (`readStream.format("kafka")`), which provides exactly-once delivery into Delta via a checkpoint. B and C invent a Kafka capability Auto Loader does not have; D misuses the `kafka` source for object storage. *(Objective: S2 Data Ingestion — choosing the correct ingestion mechanism per source type)*

2. **A** — The `binaryFile` data source "reads binary files and converts each file into a single record containing the file's raw content and metadata," producing a fixed schema of `path (StringType)`, `modificationTime (TimestampType)`, `length (LongType)`, and `content (BinaryType)`. It does no parsing or OCR — `content` is the raw bytes. B is wrong (no text extraction). C is wrong (there is a `content` column, not just a path). D is wrong: `binaryFile` is a fixed-schema format (it is explicitly listed as "Not applicable (fixed-schema)" for schema inference/evolution), so all files share one schema. *(Objective: S2 Data Ingestion — ingest Binary from cloud storage; binaryFile output schema)*

3. **A** — Native XML is a supported Auto Loader format in Databricks Runtime 14.3 LTS and above, but the row boundary is defined by the `rowTag` option, which identifies the element that becomes a DataFrame Row — without it the structure is wrong. B and D are false: XML is natively supported by `cloudFiles` with no external jar. C is wrong: `multiLine` does not define the per-row element for XML; `rowTag` does. *(Objective: S2 Data Ingestion — ingest XML from cloud storage; required rowTag option)*

4. **A** — Append-only streaming ingestion to Delta uses `outputMode("append")` (the default) plus a `checkpointLocation`; the checkpoint stores Kafka offsets and write progress, and the Delta transaction log "guarantees exactly-once processing," so the job resumes without duplicates or loss after a restart. B drops the checkpoint (no offset recovery) and `complete` is for full-result aggregations. C uses a non-streaming batch write with in-memory offsets that vanish on restart. D is invalid: per the docs, the Delta Lake sink supports append and complete modes but **not** update mode. *(Objective: S2 Data Ingestion — append-only streaming pipeline with Delta; exactly-once writes)*

5. **A** — Parquet (like ORC/Avro) encodes its schema and column types in the file metadata, so Auto Loader reads them directly. For formats that don't encode data types (JSON, CSV, XML), Auto Loader infers all columns as strings by default, and enabling type inference requires sampling files, which is costlier and error-prone. B reverses reality — CSV is text with no typed schema. C is false: `schemaHints` is optional. D is false: Auto Loader infers schema from Parquet via its metadata, no user schema required (Parquet schema inference is supported in DBR 11.3 LTS+). *(Objective: S2 Data Ingestion — columnar/self-describing formats; format-vs-schema tradeoff)*

6. **A** — Auto Loader defaults to directory listing mode; for high file volumes it offers file notification mode (classic `cloudFiles.useNotifications=true`, or the recommended file-events-on-external-location path), which "leverages file notification and queue services in your cloud infrastructure account" and "can scale Auto Loader to ingest millions of files an hour," avoiding repeated full listings. It is specific to cloud object storage. B is wrong — notification mode uses the cloud provider's native event service, not Kafka. C wrongly denies notification mode exists; `maxFilesPerTrigger` only caps batch size, not listing cost. D misuses `backfillInterval` (it schedules periodic backfill listings) and does not turn on event-based discovery. *(Objective: S2 Data Ingestion — incremental ingestion at scale; Auto Loader discovery mode selection)*
