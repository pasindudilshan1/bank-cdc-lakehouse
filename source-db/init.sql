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

-- Debezium needs the full old row on UPDATE/DELETE for proper history
ALTER TABLE customers    REPLICA IDENTITY FULL;
ALTER TABLE accounts     REPLICA IDENTITY FULL;
ALTER TABLE transactions REPLICA IDENTITY FULL;

-- keep updated_at correct automatically
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_customers_touch BEFORE UPDATE ON customers
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER trg_accounts_touch BEFORE UPDATE ON accounts
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
