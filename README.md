# Real-time Banking CDC Lakehouse

> 🚧 **Work in progress.** This repo is where I'm building the project step by step. Right now it only holds the plan. The full code will be pushed once the build is finished.
>
> ⭐ If this looks interesting, **star the repo** to follow along and get the full project when it lands.

## What I'm building

A bank data platform that captures every change in a core banking database in near real time, keeps the full history of customers and accounts (SCD Type 2), and serves a governed **Customer 360**, **fraud** and **churn** view in Power BI.

## How it will work

1. **PostgreSQL** acts as the bank's core system (customers, accounts, transactions). A Python generator keeps inserting, updating and deleting data.
2. **Debezium** reads the Postgres write-ahead log (CDC) and publishes every change as an event to **Kafka**.
3. **Azure Databricks** reads Kafka with **PySpark Structured Streaming** and builds Bronze, Silver and Gold **Delta** tables in ADLS Gen2, governed by **Unity Catalog**.
4. **Microsoft Fabric** links to the Gold tables with OneLake shortcuts (no data copy).
5. **Power BI** reads them in Direct Lake mode for fast reports.
6. Everything is deployed with **Databricks Asset Bundles** and **GitHub Actions**.

```
Postgres ──► Debezium ──► Kafka ──► Databricks (Bronze → Silver → Gold) ──► Fabric (OneLake) ──► Power BI
```

## Tech stack

| Layer | Tool |
| --- | --- |
| Source system | PostgreSQL 16 (Docker) |
| Change data capture | Debezium 2.7 on Kafka Connect |
| Event streaming | Apache Kafka (local) / Confluent Cloud |
| Processing | PySpark Structured Streaming on Azure Databricks |
| Storage | ADLS Gen2 + Delta Lake |
| Governance | Unity Catalog (grants, column masks, row filters, lineage) |
| Orchestration | Databricks Jobs via Asset Bundles |
| Serving | Microsoft Fabric Lakehouse + OneLake shortcuts |
| Reporting | Power BI Direct Lake |
| CI/CD | GitHub Actions + pytest |

## Roadmap

- [ ] **Week 1** – Local Docker stack, source database, data generator, Debezium CDC
- [ ] **Week 2** – Confluent Cloud, Azure resources, Unity Catalog, Bronze layer
- [ ] **Week 3** – Silver layer (data quality + SCD Type 2), Gold layer (star schema, Customer 360, fraud, churn)
- [ ] **Week 4** – Governance, Asset Bundles job, optional Lakeflow AUTO CDC pipeline
- [ ] **Week 5** – Fabric shortcuts and Power BI report
- [ ] **Week 6** – Tests, CI/CD, end-to-end test scenarios, demo video

## Key engineering features (planned)

- Near real-time CDC from an OLTP database with no changes to the app
- Medallion architecture (Bronze / Silver / Gold) on Delta Lake
- SCD Type 2 history with point-in-time joins
- Data quality checks and quarantine
- Column masking and row-level security for sensitive banking data
- Infrastructure and jobs defined as code, tested and deployed through CI/CD

## Status

📌 Planning done, build in progress. Watch / star this repo for updates.
