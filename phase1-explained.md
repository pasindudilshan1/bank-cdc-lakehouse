# Phase 1 Explained: The Local Docker Stack

This file explains everything in Phase 1: what we build, why, every line of `docker-compose.yaml`, the `.env` files, and every command you run.

---

## 1. What Phase 1 builds

By the end of Phase 1, one command starts four programs on your laptop:

| Container | What it is | Job in this project | Port on your laptop |
| --- | --- | --- | --- |
| `postgres` | PostgreSQL 16 database | Acts as the bank's core system (customers, accounts, transactions) | 5432 |
| `kafka` | Apache Kafka 3.7 | Stores every database change as an event, in order | 9092 |
| `connect` | Kafka Connect with Debezium | Reads changes from Postgres and writes them into Kafka | 8083 |
| `kafka-ui` | Kafka web UI (kafbat) | A website to look inside Kafka | 8080 |

How data will flow (we connect the pieces in Phase 3):

```
 Postgres  ──(changes)──►  Debezium (inside Connect)  ──(events)──►  Kafka  ──►  Kafka UI (you look here)
```

In Phase 1 we only start them and check they are healthy. No data flows yet.

---

## 2. Key concepts

### 2.1 Docker
Docker runs programs inside **containers**. A container is a small, isolated box that has the program and everything it needs. You don't install Postgres or Kafka on Windows. Docker downloads a ready-made box and runs it.

- **Image**: the recipe or template (for example `postgres:16`). It is downloaded once.
- **Container**: a running copy of an image.
- **Docker Hub / quay.io / ghcr.io**: websites (registries) where images are stored.

### 2.2 Docker Compose
Running four containers by hand would need four long commands. **Docker Compose** lets you describe all of them in one file (`docker-compose.yaml`) and start them together with `docker compose up -d`.

Compose also creates a private **network** for the containers. Inside it, each container can reach the others by **service name**. For example, `connect` reaches Kafka at `kafka:29092`, and Kafka UI reaches Connect at `http://connect:8083`.

### 2.3 YAML
YAML is the file format of `docker-compose.yaml`. Rules that matter:

- **Indentation means structure.** Use spaces, never tabs. Two spaces per level.
- `key: value` needs a **space after the colon**.
- A list item starts with `- ` (dash **and space**).
- `[a, b, c]` is a short way to write a list on one line.
- `${NAME}` is not YAML. It is Compose's way of saying "insert the value of `NAME` from `.env` here".

Example:
```yaml
services:          # level 0
  postgres:        # level 1: a service
    image: x       # level 2: a setting of that service
    ports:         # level 2: a setting that holds a list
      - "5432:5432"  # level 3: a list item
```

If `connect:` were indented 4 spaces instead of 2, YAML would think `connect` is a setting *inside* `kafka`, not its own service. That was one of the bugs we fixed.

### 2.4 Ports: `"HOST:CONTAINER"`
`"5432:5432"` means: port 5432 on **your laptop** forwards to port 5432 **inside the container**. Without this, only other containers could reach it. The quotes stop YAML from misreading numbers with colons.

### 2.5 Volumes
A container's files are lost when the container is deleted. A **volume** keeps data outside the container.

- **Named volume** (`pgdata:/var/lib/postgresql/data`): Docker manages a storage area called `pgdata`. Your database survives `docker compose down`.
- **Bind mount** (`./source-db/init.sql:/docker-entrypoint-initdb.d/01-init.sql`): a file from your project folder appears inside the container.

### 2.6 Environment variables
Settings passed into a container, like `POSTGRES_USER=bank`. Most images are configured this way. Each image reads its own list of names, and **a misspelled name is silently ignored**. That's why typos like `KAFKAA_NUM_PARTITIONS` are dangerous: no error, the setting just doesn't apply.

### 2.7 Kafka basics
- **Broker**: the Kafka server that stores messages.
- **Topic**: a named stream of messages, like a table of events. Debezium will create one topic per database table.
- **Partition**: a topic is split into partitions so it can be read in parallel. Order is guaranteed inside a partition.
- **Producer / consumer**: writes messages / reads messages.
- **Controller**: the part of Kafka that manages the cluster (which broker leads which partition, and so on).
- **KRaft**: Kafka's built-in way of running the controller. Older Kafka needed a separate program called ZooKeeper. With KRaft we need just one container.

### 2.8 CDC and Debezium
**CDC (Change Data Capture)** means capturing every insert, update and delete in a database as it happens.

Postgres writes every change to its **WAL (Write-Ahead Log)** before applying it. **Debezium** reads the WAL and turns each change into a Kafka message. The banking app doesn't need any changes, and the database isn't slowed by extra queries.

### 2.9 Kafka Connect
**Kafka Connect** is a framework for moving data in and out of Kafka using plugins called **connectors**. The `quay.io/debezium/connect` image is Kafka Connect with the Debezium plugins already installed. You control it through a REST API on port 8083 (that's what `curl` talks to).

---

## 3. The `.env` and `.env.example` files

### What they are
| File | Contains | Goes to GitHub? |
| --- | --- | --- |
| `.env` | your **real** values (passwords, API keys) | ❌ Never. It is listed in `.gitignore` |
| `.env.example` | the same keys with **sample** values | ✅ Yes, so others know what to fill in |

Docker Compose automatically reads a file named `.env` in the same folder as the compose file, and replaces every `${NAME}` with its value.

### Contents
```bash
POSTGRES_USER=bank
POSTGRES_PASSWORD=bankpass
POSTGRES_DB=corebank
# Confluent Cloud (Phase 4)
CC_BOOTSTRAP=pkc-xxxxx.<your-region>.azure.confluent.cloud:9092
CC_API_KEY=xxxxxxxx
CC_API_SECRET=xxxxxxxx
```

| Key | Meaning |
| --- | --- |
| `POSTGRES_USER` | database user that will be created |
| `POSTGRES_PASSWORD` | that user's password |
| `POSTGRES_DB` | name of the database that will be created |
| `CC_*` | Confluent Cloud settings, used in Phase 4. Ignore them for now |

Rules: `KEY=value`, no spaces around `=`, no quotes, `#` starts a comment.

### Create them
```powershell
# after writing .env.example
copy .env.example .env
```

---

## 4. `docker-compose.yaml` line by line

### 4.1 Top level
```yaml
services:
```
Everything under `services:` is one container to run. We have four.

---

### 4.2 Postgres
```yaml
  postgres:
```
The **service name**. Other containers reach this database at host `postgres`.

```yaml
    image: postgres:16
```
Use the official Postgres image, version 16. The part after `:` is the **tag** (version).

```yaml
    container_name: postgres
```
A fixed name for the container, so commands like `docker exec -it postgres ...` work. Without it, Compose would make a name like `newfolder4-postgres-1`.

```yaml
    command: ["postgres", "-c", "wal_level=logical", "-c", "max_replication_slots=4", "-c", "max_wal_senders=4"]
```
Starts Postgres with three extra settings (`-c` means "set config"):

| Setting | Why |
| --- | --- |
| `wal_level=logical` | **Most important line for CDC.** The default (`replica`) writes WAL only for copying the whole database. `logical` adds enough detail for Debezium to decode each row change |
| `max_replication_slots=4` | A **replication slot** is a bookmark that remembers how far Debezium has read in the WAL, so nothing is missed if Debezium restarts. We allow up to 4 |
| `max_wal_senders=4` | Max number of processes that can stream the WAL out at the same time |

```yaml
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
```
On first start, the Postgres image creates this user, password and database. Values come from `.env`.

```yaml
    ports:
      - "5432:5432"
```
Lets tools on your laptop (DBeaver, pgAdmin, the Python generator in Phase 2) connect at `localhost:5432`.

```yaml
    volumes:
      - ./source-db/init.sql:/docker-entrypoint-initdb.d/01-init.sql
      - pgdata:/var/lib/postgresql/data
```
| Line | Meaning |
| --- | --- |
| first | Puts your `init.sql` into a special folder. The Postgres image runs every `.sql` file in `/docker-entrypoint-initdb.d/` **once, only when the database is empty (first start)**. Phase 2 fills this file with the bank tables |
| second | Stores the actual database files in the named volume `pgdata`, so data survives restarts |

⚠️ **Important:** because `init.sql` runs only on the first start, if you change it later you must wipe the volume (`docker compose down -v`) and start again.

⚠️ That's also why we created an empty `source-db/init.sql` first. If the file doesn't exist, Docker creates a **folder** named `init.sql` instead and Postgres fails.

```yaml
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      retries: 10
```
Docker regularly asks "is Postgres ready?" using the `pg_isready` tool.

| Key | Meaning |
| --- | --- |
| `test` | The command to run. `CMD-SHELL` means run it in a shell. Exit code 0 means healthy |
| `interval: 5s` | Check every 5 seconds |
| `retries: 10` | After 10 failures in a row, mark the container **unhealthy** |

`docker compose ps` shows `healthy` once it passes. `connect` waits for this (see `depends_on` below).

---

### 4.3 Kafka
```yaml
  kafka:
    image: apache/kafka:3.7.0
    container_name: kafka
    hostname: kafka
```
Official Apache Kafka image, version 3.7.0. `hostname: kafka` sets the container's own network name to match the service name, so the addresses Kafka hands out are correct.

```yaml
    ports:
      - "9092:9092"
```
Tools on your laptop connect to Kafka at `localhost:9092`.

```yaml
    environment:
```
The Apache Kafka image turns every `KAFKA_SOMETHING_NAME` variable into the Kafka setting `something.name`. For example `KAFKA_NUM_PARTITIONS` becomes `num.partitions`.

#### Identity and role
```yaml
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
```
| Setting | Meaning |
| --- | --- |
| `NODE_ID: 1` | This server's unique ID in the cluster |
| `PROCESS_ROLES: broker,controller` | This one container does both jobs: stores messages (broker) and manages the cluster (controller). This is KRaft "combined mode", fine for a laptop |

#### Listeners (the part people get wrong most)
A **listener** is a door into Kafka: a name, a port, and a protocol.

```yaml
      KAFKA_LISTENERS: PLAINTEXT://:29092,CONTROLLER://:9093,PLAINTEXT_HOST://:9092
```
Kafka opens three doors:

| Listener name | Port | Used by |
| --- | --- | --- |
| `PLAINTEXT` | 29092 | other **containers** (connect, kafka-ui) |
| `CONTROLLER` | 9093 | Kafka's own controller traffic |
| `PLAINTEXT_HOST` | 9092 | programs on **your laptop** |

`://:29092` with nothing before the port means "listen on all network addresses".

```yaml
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:29092,PLAINTEXT_HOST://localhost:9092
```
When a client connects, Kafka replies with "for data, talk to me at address X". This line sets X for each door:

- A container that came through `PLAINTEXT` is told `kafka:29092`, a name that works inside the Docker network.
- Your laptop that came through `PLAINTEXT_HOST` is told `localhost:9092`, a name that works on Windows.

**Why two?** Your laptop can't resolve the name `kafka`, and inside a container `localhost` means the container itself. With only one address, one side would connect, then fail with the classic "connected but cannot fetch metadata" error.

```yaml
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT
```
Maps each listener **name** to a **security protocol**. All three use `PLAINTEXT` (no encryption, no login). That's fine on a laptop. In Phase 4 Confluent Cloud uses `SASL_SSL` (encrypted with an API key).

#### Controller settings
```yaml
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
```
| Setting | Meaning |
| --- | --- |
| `CONTROLLER_QUORUM_VOTERS: 1@kafka:9093` | The list of controllers that vote on cluster decisions. Format `id@host:port`. Just us: node 1 at `kafka:9093` |
| `CONTROLLER_LISTENER_NAMES: CONTROLLER` | Which listener the controller uses |
| `INTER_BROKER_LISTENER_NAME: PLAINTEXT` | Which listener brokers use to talk to each other |

#### Single-node safety settings
```yaml
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 1
```
Kafka keeps internal topics, for example `__consumer_offsets`, which remembers how far each consumer has read. By default it wants **3 copies** on 3 brokers. We have only 1 broker, so we set copies to 1. Without this, consumers and Kafka UI would hang or error.

| Setting | Meaning |
| --- | --- |
| `OFFSETS_TOPIC_REPLICATION_FACTOR` | copies of the consumer-offsets topic |
| `TRANSACTION_STATE_LOG_REPLICATION_FACTOR` | copies of the transactions topic |
| `TRANSACTION_STATE_LOG_MIN_ISR` | minimum copies that must be in sync (ISR = in-sync replicas) |

```yaml
      KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS: 0
```
When a consumer group starts, Kafka normally waits 3 seconds for more members before giving out partitions. 0 means start immediately. Faster on a laptop.

```yaml
      KAFKA_NUM_PARTITIONS: 3
```
New topics (like the ones Debezium creates) get 3 partitions by default.

---

### 4.4 Kafka Connect (Debezium)
```yaml
  connect:
    image: quay.io/debezium/connect:2.7
    container_name: connect
```
Kafka Connect 2.7 from Debezium, with the Postgres connector plugin included. It is hosted on quay.io, not Docker Hub.

```yaml
    depends_on:
      postgres:
        condition: service_healthy
      kafka:
        condition: service_started
```
Start order:
- Wait until Postgres passes its **healthcheck** (`service_healthy`).
- Wait until Kafka's container has **started** (`service_started`). Kafka has no healthcheck here, so "started" is the best we can check. Connect retries on its own if Kafka needs a few more seconds.

```yaml
    ports:
      - "8083:8083"
```
Connect's REST API. You use it with `curl` to check plugins (Phase 1) and create the connector (Phase 3).

```yaml
    environment:
      BOOTSTRAP_SERVERS: kafka:29092
      GROUP_ID: bank-connect
      CONFIG_STORAGE_TOPIC: _connect_configs
      OFFSET_STORAGE_TOPIC: _connect_offsets
      STATUS_STORAGE_TOPIC: _connect_statuses
```
| Setting | Meaning |
| --- | --- |
| `BOOTSTRAP_SERVERS: kafka:29092` | Where to find Kafka. Uses the **container** door (`PLAINTEXT`), because Connect is a container |
| `GROUP_ID: bank-connect` | Name of this Connect cluster. Several Connect workers with the same ID would share the work |
| `CONFIG_STORAGE_TOPIC` | Kafka topic where Connect saves connector settings |
| `OFFSET_STORAGE_TOPIC` | Kafka topic where Connect saves **how far it has read** in the Postgres WAL |
| `STATUS_STORAGE_TOPIC` | Kafka topic where Connect saves whether each connector is RUNNING or FAILED |

Connect keeps no state on its own disk. Everything lives in Kafka, so if you restart the container it continues where it stopped.

---

### 4.5 Kafka UI
```yaml
  kafka-ui:
    image: ghcr.io/kafbat/kafka-ui:latest
    container_name: kafka-ui
    depends_on: [kafka, connect]
```
A web app to browse topics, messages and connectors. `kafbat/kafka-ui` is the maintained version of the older `provectus/kafka-ui`. `depends_on: [kafka, connect]` is the short list form, meaning "start after these two have started".

```yaml
    ports:
      - "8080:8080"
```
Open http://localhost:8080 in your browser.

```yaml
    environment:
      KAFKA_CLUSTERS_0_NAME: local
      KAFKA_CLUSTERS_0_BOOTSTRAPSERVERS: kafka:29092
      KAFKA_CLUSTERS_0_KAFKACONNECT_0_NAME: debezium
      KAFKA_CLUSTERS_0_KAFKACONNECT_0_ADDRESS: http://connect:8083
```
The `_0_` parts are list positions: **cluster number 0** and, inside it, **Connect number 0**. The UI can show many clusters. We have one.

| Setting | Meaning |
| --- | --- |
| `CLUSTERS_0_NAME` | display name in the UI |
| `CLUSTERS_0_BOOTSTRAPSERVERS` | where Kafka is (container door) |
| `CLUSTERS_0_KAFKACONNECT_0_NAME` | display name of the Connect cluster |
| `CLUSTERS_0_KAFKACONNECT_0_ADDRESS` | Connect REST API address, so the UI can show connectors |

---

### 4.6 Named volumes
```yaml
volumes:
  pgdata:
```
At **level 0** (not inside a service). Declares the named volume `pgdata` used by Postgres. An empty value means "default settings, Docker decides where to store it".

---

## 5. Commands

### 5.1 Check before starting
```powershell
docker compose config --quiet
```
Reads the compose file and `.env` and checks them. No output means valid. Without `--quiet`, it prints the final file with all `${...}` values filled in.

```powershell
docker compose config | Select-String POSTGRES
```
Shows only lines with `POSTGRES`, to confirm `.env` was read (you should see `bank`, `corebank`).

### 5.2 Start
```powershell
docker compose up -d
```
| Part | Meaning |
| --- | --- |
| `up` | download missing images, create the network and volume, start the containers |
| `-d` | "detached": run in the background and give your terminal back |

The first run downloads around 2 GB.

### 5.3 Check status
```powershell
docker compose ps
```
Lists the containers. Expect four with status `Up`, and postgres `Up (healthy)`.

```powershell
curl -s http://localhost:8083/
```
Asks Kafka Connect for version info. `-s` means silent (no progress bar). If you get JSON back, Connect is alive. It can take 30 to 60 seconds after `up`.

```powershell
curl -s http://localhost:8083/connector-plugins | jq ".[].class"
```
Lists installed connector plugins. `jq ".[].class"` means "for every item in the list, print its `class` field". You must see:
```
"io.debezium.connector.postgresql.PostgresConnector"
```
Without jq:
```powershell
(Invoke-RestMethod http://localhost:8083/connector-plugins).class
```

Open **http://localhost:8080** to see Kafka UI. You'll see only Connect's internal topics (`_connect_configs` and others) for now. Bank topics appear in Phase 3.

### 5.4 Look inside
```powershell
docker compose logs -f connect
```
Shows the logs of one service. `-f` means "follow" (keep printing new lines). Press `Ctrl+C` to stop watching; the container keeps running. Use `postgres` or `kafka` instead of `connect` for the others.

```powershell
docker exec -it postgres psql -U bank -d corebank
```
Opens a SQL prompt inside the Postgres container.

| Part | Meaning |
| --- | --- |
| `exec` | run a command in a running container |
| `-it` | interactive terminal, so you can type |
| `postgres` | the container name |
| `psql -U bank -d corebank` | the Postgres client, as user `bank`, on database `corebank` |

Useful inside psql: `SHOW wal_level;` (should say `logical`), `\dt` (list tables), `\q` (quit).

### 5.5 Stop
```powershell
docker compose down
```
Stops and removes the containers and network. **Data is kept** in the `pgdata` volume.

```powershell
docker compose down -v
```
Same, plus `-v` deletes volumes, so **all database data is erased**. Use it when you want a fresh start, for example after changing `init.sql`.

### 5.6 Save your work in Git
```powershell
git add .env.example docker-compose.yaml source-db .gitignore
git status
git commit -m "Phase 1: local Docker stack"
```
Check that `.env` is **not** in the `git status` list. Don't push yet; you'll push the full project when the tutorial is finished.

---

## 6. Troubleshooting

| Problem | Likely cause | Fix |
| --- | --- | --- |
| `variable is not set. Defaulting to a blank string` | `.env` is empty or missing | Fill `.env`, make sure it's in the same folder as the compose file |
| `yaml: line X: mapping values are not allowed` | missing space after `:` or wrong indentation | Check that line and the line above |
| `port is already allocated` | another program uses 5432, 9092, 8083 or 8080 | Stop that program (often a local Postgres install) or change the left number, e.g. `"5433:5432"` |
| postgres stays `unhealthy` | wrong user/db in `.env`, or a broken `init.sql` | `docker compose logs postgres` |
| `curl` to 8083 returns nothing | Connect is still starting | Wait 30 to 60 seconds and try again; check `docker compose logs connect` |
| Connect logs say it can't reach Kafka | wrong `BOOTSTRAP_SERVERS` or listener typo | Must be `kafka:29092`; check the three listener lines |
| `init.sql` is a folder | the file didn't exist when Docker started | `docker compose down -v`, delete the folder, create the file, `up -d` again |
| Changed `init.sql` but nothing happened | it only runs on an empty database | `docker compose down -v` then `docker compose up -d` |
| Docker commands hang or fail | Docker Desktop isn't running | Open Docker Desktop, wait for "Engine running" |

---

## 7. Phase 1 checklist

- [ ] `jq --version` and `java -version` work
- [ ] `.env.example` written, copied to `.env`
- [ ] `source-db/init.sql` exists (empty is fine)
- [ ] `docker compose config --quiet` shows no errors
- [ ] `docker compose up -d` finished
- [ ] `docker compose ps` shows 4 containers, postgres `healthy`
- [ ] `curl` lists `PostgresConnector`
- [ ] http://localhost:8080 opens
- [ ] `SHOW wal_level;` in psql says `logical`
- [ ] Committed to Git, `.env` not included

Next: **Phase 2**, the bank database schema (`init.sql`) and the Python data generator.
