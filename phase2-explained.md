# Phase 2 Explained: Bank Database and Data Generator

This file explains everything in Phase 2: the bank database design, every part of `init.sql`, every function in the Python generator, every command you run, and the two real problems we hit and fixed.

---

## 1. What Phase 2 builds

Phase 1 started an empty Postgres. Phase 2 turns it into a **live core banking system**:

1. **`source-db/init.sql`** creates three tables: `customers`, `accounts`, `transactions`.
2. **`generator/generate_bank_activity.py`** behaves like a busy bank: it opens accounts, posts transactions, changes customer details, closes accounts and injects fraud patterns, about 5 events per second.

```
 generate_bank_activity.py  ──(INSERT / UPDATE)──►  Postgres (corebank)  ──(WAL)──►  Debezium in Phase 3
```

Why we need a generator: CDC only has something to capture if the data **changes**. A static database gives Debezium nothing to stream.

---

## 2. Key concepts

### 2.1 OLTP database
**OLTP (Online Transaction Processing)** is the kind of database a bank app writes to: many small, fast inserts and updates, one row at a time. Postgres is our OLTP system. Later, Databricks is the **analytics** side, which reads lots of rows at once. CDC is the bridge between the two.

### 2.2 Primary key and foreign key
- **Primary key**: the unique ID of a row (`customer_id`). No two rows can share it. Debezium uses it as the **Kafka message key**, so all changes to one customer go to the same partition, in order.
- **Foreign key** (`REFERENCES`): a column that must match a primary key in another table. `accounts.customer_id` must be a real customer. This stops orphan data.

### 2.3 The data model
```
customers (1) ──< accounts (many) ──< transactions (many)
```
One customer has many accounts. One account has many transactions. This is called a **one-to-many** relationship.

### 2.4 WAL and replica identity
Postgres writes every change to the **WAL (Write-Ahead Log)** before applying it. In Phase 1 we set `wal_level=logical` so the WAL contains row-level detail.

**Replica identity** decides how much of the **old row** goes into the WAL on UPDATE and DELETE:

| Setting | Old row in WAL | Result for CDC |
| --- | --- | --- |
| `DEFAULT` | only the primary key | you know *which* row changed, but not what it was before |
| `FULL` | the whole old row | Debezium sends a full **before** and **after** image |

We use `FULL` because SCD Type 2 (Phase 7) needs to know old values.

### 2.5 SCD Type 2 (why the generator changes customers)
**SCD (Slowly Changing Dimension) Type 2** keeps every version of a record instead of overwriting it:

| customer_id | city | valid_from | valid_to |
| --- | --- | --- | --- |
| 42 | Boston | 2026-10-01 | 2026-10-15 |
| 42 | Denver | 2026-10-15 | (current) |

The generator's `change_customer()` creates exactly these changes, so Phase 7 has history to build.

### 2.6 Trigger
A **trigger** is code Postgres runs automatically when something happens. Ours runs **before every UPDATE** and sets `updated_at` to now. Later layers use `updated_at` to put versions in the right order.

### 2.7 Synthetic data and Faker
Real bank data is private, so we make **synthetic** (fake but realistic) data. The **Faker** library generates names, emails, cities, phone numbers and company names.

### 2.8 Bad data on purpose
Real systems have messy data. The generator gives **3% of customers the email `not-an-email`**. In Phase 7 your data quality checks must catch these and move them to **quarantine**. Without bad data, you couldn't prove your checks work.

### 2.9 Python virtual environment
A **virtual environment** (`.venv`) is a private Python folder for one project. Packages installed there don't affect other projects, and other projects can't break this one. `.venv/` is in `.gitignore`, so it never goes to GitHub.

---

## 3. `source-db/init.sql` explained

This file runs **automatically, once**, the first time the Postgres container starts with an empty data volume.

### 3.1 Table `customers`
```sql
CREATE TABLE customers (
    customer_id    SERIAL PRIMARY KEY,
    first_name     VARCHAR(60)  NOT NULL,
    last_name      VARCHAR(60)  NOT NULL,
    email          VARCHAR(120),
    phone          VARCHAR(30),
    national_id    VARCHAR(20)  NOT NULL,
    date_of_birth  DATE,
    city           VARCHAR(60),
    branch         VARCHAR(20)  NOT NULL,      -- NORTH / SOUTH / EAST / WEST
    home_country   CHAR(2)      NOT NULL DEFAULT 'US',
    segment        VARCHAR(20)  NOT NULL,      -- RETAIL / PREMIUM / BUSINESS
    kyc_status     VARCHAR(20)  NOT NULL,      -- PENDING / VERIFIED / REJECTED
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);
```

| Column | Type | Meaning and use later |
| --- | --- | --- |
| `customer_id` | `SERIAL PRIMARY KEY` | Auto-numbered unique ID (1, 2, 3...) |
| `first_name`, `last_name` | `VARCHAR(60)` | Name, up to 60 characters |
| `email` | `VARCHAR(120)` | Can be empty. Sometimes invalid on purpose. **Masked** in Phase 10 |
| `phone` | `VARCHAR(30)` | **Masked** in Phase 10 |
| `national_id` | `VARCHAR(20)` | ID card number. Sensitive, **masked** in Phase 10 |
| `date_of_birth` | `DATE` | Used for age groups in reports |
| `city` | `VARCHAR(60)` | Changes over time, so it is tracked with SCD2 |
| `branch` | `VARCHAR(20)` | Home branch. Used for **row-level security** in Phase 10 (a NORTH manager sees only NORTH customers) |
| `home_country` | `CHAR(2)` | Country code. A transaction in a different country is a fraud signal |
| `segment` | `VARCHAR(20)` | RETAIL, PREMIUM or BUSINESS. Changes over time |
| `kyc_status` | `VARCHAR(20)` | KYC = Know Your Customer (identity check). PENDING, VERIFIED or REJECTED |
| `created_at` | `TIMESTAMPTZ` | When the customer joined. Filled automatically |
| `updated_at` | `TIMESTAMPTZ` | Last change time. Kept correct by the trigger |

**Data types used:**

| Type | Meaning |
| --- | --- |
| `SERIAL` | Integer that Postgres numbers automatically |
| `BIGSERIAL` | Same, but much bigger range (used for transactions, which grow fastest) |
| `VARCHAR(n)` | Text up to n characters |
| `CHAR(n)` | Text of exactly n characters (codes like `US`, `USD`) |
| `DATE` | Date only |
| `TIMESTAMPTZ` | Date and time **with timezone**. Always use this for event times |
| `NUMERIC(18,2)` | Exact decimal: 18 digits total, 2 after the point. **Always use this for money.** `float` gives rounding errors like `0.1 + 0.2 = 0.30000000000000004` |

**Constraints:**

| Keyword | Meaning |
| --- | --- |
| `PRIMARY KEY` | Unique and never empty |
| `NOT NULL` | A value is required |
| `DEFAULT x` | Used when the insert doesn't give a value |
| `UNIQUE` | No two rows can have the same value |
| `REFERENCES t(col)` | Foreign key: the value must exist in table `t` |

`--` starts a comment in SQL. The comments list the allowed values.

### 3.2 Table `accounts`
```sql
CREATE TABLE accounts (
    account_id     SERIAL PRIMARY KEY,
    customer_id    INT NOT NULL REFERENCES customers(customer_id),
    account_number VARCHAR(20) UNIQUE NOT NULL,
    account_type   VARCHAR(20) NOT NULL,       -- SAVINGS / CURRENT / FIXED
    currency       CHAR(3)     NOT NULL DEFAULT 'USD',
    balance        NUMERIC(18,2) NOT NULL DEFAULT 0,
    status         VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE / FROZEN / CLOSED
    opened_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

| Column | Meaning |
| --- | --- |
| `account_id` | Internal unique ID |
| `customer_id` | Owner. **Foreign key** to `customers` |
| `account_number` | The number printed on a bank card or statement. `UNIQUE` |
| `account_type` | SAVINGS, CURRENT (everyday) or FIXED (fixed deposit) |
| `currency` | Default USD |
| `balance` | Money in the account, updated on every transaction |
| `status` | ACTIVE, FROZEN or CLOSED. CLOSED accounts feed **churn** analysis in Phase 8 |
| `opened_at` | When the account was opened |
| `updated_at` | Kept correct by the trigger |

### 3.3 Table `transactions`
```sql
CREATE TABLE transactions (
    txn_id         BIGSERIAL PRIMARY KEY,
    account_id     INT NOT NULL REFERENCES accounts(account_id),
    txn_type       VARCHAR(20) NOT NULL,       -- DEPOSIT / WITHDRAWAL / TRANSFER_OUT / TRANSFER_IN / CARD_PAYMENT
    amount         NUMERIC(18,2) NOT NULL,
    channel        VARCHAR(20) NOT NULL,       -- ATM / MOBILE / BRANCH / CARD / ONLINE
    merchant       VARCHAR(100),
    country        CHAR(2) NOT NULL,
    status         VARCHAR(20) NOT NULL DEFAULT 'POSTED',
    txn_ts         TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

| Column | Meaning |
| --- | --- |
| `txn_id` | Unique ID. `BIGSERIAL` because this table grows the fastest |
| `account_id` | Which account. **Foreign key** to `accounts` |
| `txn_type` | Money in: DEPOSIT, TRANSFER_IN. Money out: WITHDRAWAL, TRANSFER_OUT, CARD_PAYMENT |
| `amount` | Always positive. The type decides plus or minus |
| `channel` | Where it happened: ATM, MOBILE, BRANCH, CARD, ONLINE |
| `merchant` | Shop or company name |
| `country` | Where it happened. Foreign countries are a fraud signal |
| `status` | POSTED by default |
| `txn_ts` | When it happened. This is the **event time** used in the Gold fact table |

Transactions are **append-only** in this bank: they are inserted, never updated. Customers and accounts are **updated**, which is why only they get the trigger.

### 3.4 Replica identity
```sql
ALTER TABLE customers    REPLICA IDENTITY FULL;
ALTER TABLE accounts     REPLICA IDENTITY FULL;
ALTER TABLE transactions REPLICA IDENTITY FULL;
```
Makes Postgres write the **whole old row** to the WAL on UPDATE and DELETE (see section 2.4). Without this, Debezium's `before` field would contain only the ID.

### 3.5 The trigger
```sql
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$ LANGUAGE plpgsql;
```

| Part | Meaning |
| --- | --- |
| `CREATE OR REPLACE FUNCTION touch_updated_at()` | Create a function with this name (replace it if it exists) |
| `RETURNS trigger` | This function is meant to be called by a trigger |
| `$$ ... $$` | Marks the start and end of the function body |
| `NEW` | The row as it **will be saved** after the update |
| `NEW.updated_at = now();` | Overwrite `updated_at` with the current time |
| `RETURN NEW;` | Save the modified row |
| `LANGUAGE plpgsql` | Written in PL/pgSQL, Postgres's built-in programming language |

```sql
CREATE TRIGGER trg_customers_touch BEFORE UPDATE ON customers
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER trg_accounts_touch BEFORE UPDATE ON accounts
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
```

| Part | Meaning |
| --- | --- |
| `BEFORE UPDATE` | Run just before the row is changed, so we can still edit it |
| `ON customers` | Only for this table |
| `FOR EACH ROW` | Once per changed row (not once per statement) |
| `EXECUTE FUNCTION touch_updated_at()` | The function to run |

### 3.6 The golden rule of `init.sql`
Postgres runs files in `/docker-entrypoint-initdb.d/` **only when the data volume is empty**. If the volume already has a database, the log says:
```
PostgreSQL Database directory appears to contain a database; Skipping initialization
```
**Every time you change `init.sql`:**
```powershell
docker compose down -v
docker compose up -d
```

---

## 4. `generator/requirements.txt` explained
```text
psycopg[binary]==3.2.*
Faker==30.*
python-dotenv==1.*
```

| Line | Meaning |
| --- | --- |
| `psycopg[binary]==3.2.*` | Postgres driver for Python, version 3.2.x. `[binary]` means pre-compiled, so it installs on Windows without a C compiler |
| `Faker==30.*` | Fake data library, version 30.x |
| `python-dotenv==1.*` | Reads `.env` files into environment variables |

`==3.2.*` pins the major and minor version but allows bug-fix updates. Pinning stops a future release from breaking your project.

---

## 5. `generator/generate_bank_activity.py` explained

### 5.1 Imports and setup
```python
import argparse, os, random, time
from decimal import Decimal

import psycopg
from dotenv import load_dotenv
from faker import Faker
```

| Import | Used for |
| --- | --- |
| `argparse` | Reading command-line options like `--rate 5` |
| `os` | Reading environment variables and building file paths |
| `random` | Random choices (which action, which account, amounts) |
| `time` | `sleep` between events |
| `Decimal` | Exact money values, matching Postgres `NUMERIC` |
| `psycopg` | Talking to Postgres |
| `load_dotenv` | Loading `.env` |
| `Faker` | Fake names, emails and so on |

```python
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
```
`__file__` is this script's path. `dirname` is its folder (`generator`). `".."` goes one folder up to the project root, where `.env` is. So the script uses **the same user and password as Docker**, from one place.

```python
fake = Faker()
BRANCHES = ["NORTH", "SOUTH", "EAST", "WEST"]
SEGMENTS = ["RETAIL", "PREMIUM", "BUSINESS"]
CHANNELS = ["ATM", "MOBILE", "BRANCH", "CARD", "ONLINE"]
```
One Faker object for the whole script, and the allowed values for random choices. Capital names are a Python convention for constants.

### 5.2 `connect()`
```python
def connect():
    return psycopg.connect(
        host="localhost", port=5433,
        user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.environ["POSTGRES_DB"], autocommit=True,
    )
```

| Argument | Meaning |
| --- | --- |
| `host="localhost"` | The database is on this machine (through Docker's port mapping) |
| `port=5433` | Docker's Postgres is published on **5433**, because a Windows PostgreSQL 18 already uses 5432 (see section 8) |
| `user`, `password`, `dbname` | From `.env`. `os.environ["X"]` fails loudly if X is missing, which is better than a silent wrong value |
| `autocommit=True` | Every statement is saved immediately. Without it, changes would wait in an open transaction and Debezium wouldn't see them |

### 5.3 `new_customer(cur)`
```python
def new_customer(cur):
    cur.execute(
        """INSERT INTO customers (first_name, last_name, email, phone, national_id, date_of_birth,
                                  city, branch, home_country, segment, kyc_status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'US',%s,%s) RETURNING customer_id""",
        (fake.first_name(), fake.last_name(),
         fake.email() if random.random() > 0.03 else "not-an-email",
         fake.phone_number()[:30], fake.bothify("#########V"),
         fake.date_of_birth(minimum_age=18, maximum_age=85), fake.city(),
         random.choice(BRANCHES), random.choice(SEGMENTS),
         random.choice(["PENDING", "VERIFIED", "VERIFIED", "VERIFIED"])),
    )
    cid = cur.fetchone()[0]
    new_account(cur, cid)
```

| Part | Meaning |
| --- | --- |
| `cur` | A **cursor**: the object that sends SQL and reads results |
| `%s` | A **placeholder**. psycopg fills it safely with the values in the tuple. Never build SQL with string `+` or f-strings, because that allows **SQL injection** |
| `random.random() > 0.03` | `random()` gives 0.0 to 1.0. 97% of the time a real email, 3% `"not-an-email"` |
| `fake.phone_number()[:30]` | Cut to 30 characters to fit `VARCHAR(30)` |
| `fake.bothify("#########V")` | `#` becomes a random digit: a 9-digit ID ending in V (a national ID format) |
| `["PENDING", "VERIFIED", "VERIFIED", "VERIFIED"]` | Listing VERIFIED 3 times makes it 75% likely. A simple way to weight random choices |
| `RETURNING customer_id` | Postgres sends back the new auto-numbered ID |
| `cur.fetchone()[0]` | Reads that ID |
| `new_account(cur, cid)` | Every new customer gets a first account |

### 5.4 `new_account(cur, cid)`
```python
def new_account(cur, cid):
    cur.execute(
        """INSERT INTO accounts (customer_id, account_number, account_type, balance)
           VALUES (%s, %s, %s, %s)""",
        (cid, fake.unique.bothify("ACC##########"), random.choice(["SAVINGS", "CURRENT", "FIXED"]),
         Decimal(random.randint(100, 50000))),
    )
```

| Part | Meaning |
| --- | --- |
| `fake.unique.bothify("ACC##########")` | `ACC` + 10 random digits. `.unique` makes Faker never repeat a value, matching the `UNIQUE` column |
| `Decimal(random.randint(100, 50000))` | Starting balance between 100 and 50,000, as an exact decimal |
| Not given: `currency`, `status`, `opened_at` | Filled by the `DEFAULT` values in the table |

### 5.5 `post_txn(cur, account_id=None, amount=None, country="US")`
```python
def post_txn(cur, account_id=None, amount=None, country="US"):
    if account_id is None:
        cur.execute("SELECT account_id FROM accounts WHERE status='ACTIVE' ORDER BY random() LIMIT 1")
        row = cur.fetchone()
        if not row:
            return
        account_id = row[0]
    txn_type = random.choice(["DEPOSIT", "WITHDRAWAL", "CARD_PAYMENT", "TRANSFER_OUT", "TRANSFER_IN"])
    amount = amount or Decimal(random.randint(5, 2000))
    sign = 1 if txn_type in ("DEPOSIT", "TRANSFER_IN") else -1
    cur.execute(
        """INSERT INTO transactions (account_id, txn_type, amount, channel, merchant, country)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (account_id, txn_type, amount, random.choice(CHANNELS), fake.company(), country),
    )
    cur.execute("UPDATE accounts SET balance = balance + %s WHERE account_id = %s", (sign * amount, account_id))
```

| Part | Meaning |
| --- | --- |
| `account_id=None` etc. | **Default arguments.** Called with nothing, it picks everything at random. `fraud_burst` passes its own values |
| `ORDER BY random() LIMIT 1` | Pick one random active account. Fine for small tables, slow on millions of rows |
| `if not row: return` | No active accounts, so do nothing |
| `amount or Decimal(...)` | Use the given amount, otherwise a random 5 to 2,000 |
| `sign` | +1 for money in, -1 for money out |
| `INSERT INTO transactions` | Records the transaction (an **insert** event for CDC) |
| `UPDATE accounts SET balance = balance + ...` | Changes the balance (an **update** event for CDC). `balance + x` is done inside Postgres, so it is safe even if two updates happen at once |

So **one transaction produces two CDC events**: an insert on `transactions` and an update on `accounts`.

Note: balances can go negative because the generator doesn't check for overdraft. That's fine for this project, and it's a nice extra data quality rule to add in Phase 7.

### 5.6 `change_customer(cur)`
```python
def change_customer(cur):
    cur.execute("SELECT customer_id FROM customers ORDER BY random() LIMIT 1")
    row = cur.fetchone()
    if not row:
        return
    change = random.choice(["city", "segment", "kyc", "email"])
    if change == "city":
        cur.execute("UPDATE customers SET city=%s WHERE customer_id=%s", (fake.city(), row[0]))
    elif change == "segment":
        cur.execute("UPDATE customers SET segment=%s WHERE customer_id=%s", (random.choice(SEGMENTS), row[0]))
    elif change == "kyc":
        cur.execute("UPDATE customers SET kyc_status='VERIFIED' WHERE customer_id=%s", (row[0],))
    else:
        cur.execute("UPDATE customers SET email=%s WHERE customer_id=%s", (fake.email(), row[0]))
```
Picks a random customer and changes one thing: moves city, changes segment, completes KYC, or changes email. **These updates are the raw material for SCD Type 2.** The trigger updates `updated_at` automatically.

`(row[0],)` has a trailing comma because a one-item **tuple** in Python needs it. `(row[0])` is just a number in brackets.

### 5.7 `close_account(cur)`
```python
def close_account(cur):
    cur.execute("UPDATE accounts SET status='CLOSED', balance=0 WHERE account_id = "
                "(SELECT account_id FROM accounts WHERE status='ACTIVE' ORDER BY random() LIMIT 1)")
```
Closes one random active account in a single statement, using a **subquery** (the `SELECT` in brackets) to choose it. Closed accounts are the **churn** signal in Phase 8.

Two strings next to each other (`"..." "..."`) are joined automatically by Python.

### 5.8 `fraud_burst(cur)`
```python
def fraud_burst(cur):
    cur.execute("SELECT account_id FROM accounts WHERE status='ACTIVE' ORDER BY random() LIMIT 1")
    row = cur.fetchone()
    if row:
        for _ in range(8):
            post_txn(cur, row[0], Decimal(random.randint(400, 3000)), country=random.choice(["NG", "RU", "BR"]))
```
On **one** account, posts **8 large transactions (400 to 3,000)** from **Nigeria, Russia or Brazil**, all within a fraction of a second. Three classic fraud signals at once:
1. **High velocity**: many transactions in a short time
2. **Unusual location**: the customer's home country is US
3. **High amounts**

Your Gold fraud table in Phase 8 should flag these accounts. `for _ in range(8)` means "repeat 8 times". `_` means "I don't need the counter".

### 5.9 `main()`
```python
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rate", type=float, default=5, help="events per second")
    parser.add_argument("--seed-customers", type=int, default=200)
    args = parser.parse_args()
```
Defines two command-line options:

| Option | Default | Meaning |
| --- | --- | --- |
| `--rate` | 5 | events per second |
| `--seed-customers` | 200 | how many customers to create on the first run |

Examples: `--rate 1` (slow, easy to watch), `--rate 20` (busy bank), `--seed-customers 1000`.

```python
    with connect() as conn, conn.cursor() as cur:
```
Opens a connection and a cursor. `with` closes them automatically when the script stops, even after an error or Ctrl+C.

```python
        cur.execute("SELECT count(*) FROM customers")
        if cur.fetchone()[0] == 0:
            print(f"Seeding {args.seed_customers} customers...")
            for _ in range(args.seed_customers):
                new_customer(cur)
```
**Seeding**: only on the first run (empty table), create 200 customers, each with an account, so transactions have accounts to use. On later runs this is skipped.

```python
        actions = [post_txn] * 80 + [new_customer] * 5 + [change_customer] * 8 + \
                  [lambda c: new_account(c, random.randint(1, 50))] * 3 + [close_account] * 2 + [fraud_burst] * 1
```
A list of 99 **functions**. `[post_txn] * 80` is a list with `post_txn` 80 times. Picking one at random gives these odds:

| Action | Entries | Chance |
| --- | --- | --- |
| `post_txn` | 80 | about 81% |
| `change_customer` | 8 | about 8% |
| `new_customer` | 5 | about 5% |
| extra account for an existing customer | 3 | about 3% |
| `close_account` | 2 | about 2% |
| `fraud_burst` | 1 | about 1% |

`lambda c: new_account(c, random.randint(1, 50))` is a **small unnamed function**. It gives an extra account to one of the first 50 customers, so some customers have several accounts. The `\` at the end of the line continues the statement on the next line.

```python
        while True:
            random.choice(actions)(cur)
            time.sleep(1 / args.rate)
```
Forever: pick an action, call it with the cursor, wait. With `--rate 5`, it waits `1 / 5 = 0.2` seconds.

```python
if __name__ == "__main__":
    main()
```
Run `main()` only when the file is run directly (`python generate_bank_activity.py`), not when another file imports it. This lets you import its functions in tests later.

---

## 6. Commands

### 6.1 Rebuild the database
```powershell
docker compose down -v
docker compose up -d
docker compose ps
```
`down -v` deletes the old empty database volume. `up -d` creates a new one, and Postgres runs `init.sql`. Wait for `healthy`.

### 6.2 Check the database
```powershell
docker exec -it postgres psql -U bank -d corebank -c "\dt"
docker exec -it postgres psql -U bank -d corebank -c "SHOW wal_level;"
```
`-c "..."` runs one command and exits. `\dt` lists tables (expect accounts, customers, transactions). `wal_level` must be `logical`.

Other useful psql commands (after `docker exec -it postgres psql -U bank -d corebank`):

| Command | Meaning |
| --- | --- |
| `\d customers` | show columns, keys and triggers of a table |
| `SELECT relreplident FROM pg_class WHERE relname='customers';` | `f` means replica identity FULL |
| `\q` | quit |

### 6.3 Python environment
```powershell
cd generator
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

| Command | Meaning |
| --- | --- |
| `python -m venv .venv` | Create a virtual environment in the `.venv` folder |
| `.venv\Scripts\activate` | Use it in this terminal. The prompt starts with `(.venv)` |
| `pip install -r requirements.txt` | Install every package in the file |
| `deactivate` | Leave the virtual environment |

If activation says "running scripts is disabled": run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

### 6.4 Run the generator
```powershell
python generate_bank_activity.py --rate 5
```
Expected:
```
Seeding 200 customers...
Generating activity. Ctrl+C to stop.
```
Leave it running. Use a second terminal for checks. **Ctrl+C** stops it.

### 6.5 Check data is arriving
```powershell
docker exec -it postgres psql -U bank -d corebank -c "SELECT count(*) FROM transactions;"
```
Run it twice. The number must grow.

More checks:
```sql
SELECT segment, count(*) FROM customers GROUP BY segment;          -- mix of segments
SELECT count(*) FROM customers WHERE email = 'not-an-email';       -- about 3% bad emails
SELECT country, count(*) FROM transactions GROUP BY country;       -- mostly US, some NG/RU/BR
SELECT status, count(*) FROM accounts GROUP BY status;             -- some CLOSED
SELECT customer_id, city, updated_at FROM customers
 WHERE updated_at > created_at + interval '1 second' LIMIT 5;      -- customers that changed
```

### 6.6 Save your work in Git
```powershell
git add source-db/init.sql generator/requirements.txt generator/generate_bank_activity.py docker-compose.yaml
git status
git commit -m "Phase 2: bank schema and data generator"
```
Make sure `.venv` and `.env` are **not** in `git status`. Don't push yet.

---

## 7. How this connects to the next phases

| What Phase 2 creates | Used in |
| --- | --- |
| Inserts, updates on 3 tables | Phase 3: Debezium turns them into Kafka events |
| `REPLICA IDENTITY FULL` | Phase 3: full `before` images in each event |
| Customer changes (city, segment, KYC, email) | Phase 7: SCD Type 2 history |
| `not-an-email` rows | Phase 7: data quality checks and quarantine |
| `updated_at` | Phase 7: ordering versions |
| `txn_ts` | Phase 8: point-in-time joins and the fact table |
| Fraud bursts | Phase 8: fraud alerts |
| Closed accounts | Phase 8: churn analysis |
| `email`, `phone`, `national_id`, `branch` | Phase 10: column masks and row filters |

---

## 8. Problems we hit and how we fixed them

### Problem 1: `password authentication failed for user "bank"`
**Cause:** a PostgreSQL 18 installed on Windows (service `postgresql-x64-18`) was also listening on port 5432. The generator connected to that one, which has no user `bank`.

**How to see it:**
```powershell
netstat -ano | findstr :5432          # two processes listening
Get-Service *postgres*                 # postgresql-x64-18 Running
```

**Fix:** publish Docker's Postgres on another laptop port.
- `docker-compose.yaml`: `- "5433:5432"`
- `generate_bank_activity.py`: `port=5433`

Inside Docker nothing changed. Debezium (Phase 3) still connects to `postgres:5432` over the Docker network. Only tools on your laptop use 5433.

### Problem 2: `relation "customers" does not exist`
**Cause:** the `pgdata` volume was created when `init.sql` was empty. On the next start Postgres logged `Skipping initialization`, so the tables were never created.

**Fix:**
```powershell
docker compose down -v
docker compose up -d
```

### Other errors you might see

| Error | Cause | Fix |
| --- | --- | --- |
| `KeyError: 'POSTGRES_USER'` | `.env` not found or empty | `.env` must be in the project root with values filled in |
| `ModuleNotFoundError: No module named 'psycopg'` | virtual environment not active, or packages not installed | `.venv\Scripts\activate`, then `pip install -r requirements.txt` |
| `Connection refused` | Postgres container not running | `docker compose ps`, then `docker compose up -d` |
| `duplicate key value violates unique constraint` | rare repeated account number after restarting the script | just run it again |
| `insert or update ... violates foreign key constraint` | an extra account was created for a customer ID that doesn't exist | happens only if seeding made fewer than 50 customers; use the default 200 |

---

## 9. Phase 2 checklist

- [ ] `source-db/init.sql` has the 3 tables, replica identity and triggers
- [ ] `docker compose down -v` and `up -d` done after writing `init.sql`
- [ ] `\dt` shows accounts, customers, transactions
- [ ] `generator/requirements.txt` and `generate_bank_activity.py` created
- [ ] `.venv` created and packages installed
- [ ] Generator printed `Seeding 200 customers...` and is running
- [ ] Transaction count keeps growing
- [ ] Some `not-an-email` customers, some foreign transactions, some CLOSED accounts exist
- [ ] Committed to Git, without `.venv` and `.env`

Next: **Phase 3**, the Debezium connector, so every change streams into Kafka in real time.
