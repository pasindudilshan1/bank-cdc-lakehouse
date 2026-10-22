"""Simulates a live core banking system. Run: python generate_bank_activity.py --rate 5"""
import argparse, os, random, time
from decimal import Decimal

import psycopg
from dotenv import load_dotenv
from faker import Faker

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
fake = Faker()
BRANCHES = ["NORTH", "SOUTH", "EAST", "WEST"]
SEGMENTS = ["RETAIL", "PREMIUM", "BUSINESS"]
CHANNELS = ["ATM", "MOBILE", "BRANCH", "CARD", "ONLINE"]


def connect():
    return psycopg.connect(
        host="localhost", port=5433,
        user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.environ["POSTGRES_DB"], autocommit=True,
    )


def new_customer(cur):
    cur.execute(
        """INSERT INTO customers (first_name, last_name, email, phone, national_id, date_of_birth,
                                  city, branch, home_country, segment, kyc_status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'US',%s,%s) RETURNING customer_id""",
        (fake.first_name(), fake.last_name(),
         fake.email() if random.random() > 0.03 else "not-an-email",   # 3% bad data on purpose
         fake.phone_number()[:30], fake.bothify("#########V"),
         fake.date_of_birth(minimum_age=18, maximum_age=85), fake.city(),
         random.choice(BRANCHES), random.choice(SEGMENTS),
         random.choice(["PENDING", "VERIFIED", "VERIFIED", "VERIFIED"])),
    )
    cid = cur.fetchone()[0]
    new_account(cur, cid)


def new_account(cur, cid):
    cur.execute(
        """INSERT INTO accounts (customer_id, account_number, account_type, balance)
           VALUES (%s, %s, %s, %s)""",
        (cid, fake.unique.bothify("ACC##########"), random.choice(["SAVINGS", "CURRENT", "FIXED"]),
         Decimal(random.randint(100, 50000))),
    )


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


def change_customer(cur):
    """Creates SCD2 history: customer moves city, changes segment, or gets KYC verified."""
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


def close_account(cur):
    cur.execute("UPDATE accounts SET status='CLOSED', balance=0 WHERE account_id = "
                "(SELECT account_id FROM accounts WHERE status='ACTIVE' ORDER BY random() LIMIT 1)")


def fraud_burst(cur):
    """Many card payments from a foreign country in a short time -> should trigger a fraud alert."""
    cur.execute("SELECT account_id FROM accounts WHERE status='ACTIVE' ORDER BY random() LIMIT 1")
    row = cur.fetchone()
    if row:
        for _ in range(8):
            post_txn(cur, row[0], Decimal(random.randint(400, 3000)), country=random.choice(["NG", "RU", "BR"]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rate", type=float, default=5, help="events per second")
    parser.add_argument("--seed-customers", type=int, default=200)
    args = parser.parse_args()

    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM customers")
        if cur.fetchone()[0] == 0:
            print(f"Seeding {args.seed_customers} customers...")
            for _ in range(args.seed_customers):
                new_customer(cur)
        print("Generating activity. Ctrl+C to stop.")
        actions = [post_txn] * 80 + [new_customer] * 5 + [change_customer] * 8 + \
                  [lambda c: new_account(c, random.randint(1, 50))] * 3 + [close_account] * 2 + [fraud_burst] * 1
        while True:
            random.choice(actions)(cur)
            time.sleep(1 / args.rate)


if __name__ == "__main__":
    main()
