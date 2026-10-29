-- QueryMind-AI database schema.
-- Run with the administrative connection, before db/runtime_role.sql.

CREATE TABLE IF NOT EXISTS public.sales_transactions (
    transaction_id text PRIMARY KEY,
    order_date date NOT NULL,
    product text NOT NULL,
    category text NOT NULL,
    region text NOT NULL,
    sales_channel text NOT NULL,
    quantity integer NOT NULL,
    unit_price numeric(12, 2) NOT NULL,
    discount_amount numeric(12, 2) NOT NULL DEFAULT 0,
    status text NOT NULL,
    CONSTRAINT ck_sales_quantity_nonnegative CHECK (quantity >= 0),
    CONSTRAINT ck_sales_unit_price_nonnegative CHECK (unit_price >= 0),
    CONSTRAINT ck_sales_discount_nonnegative CHECK (discount_amount >= 0)
);

CREATE INDEX IF NOT EXISTS ix_sales_transactions_order_date
    ON public.sales_transactions (order_date);
CREATE INDEX IF NOT EXISTS ix_sales_transactions_product
    ON public.sales_transactions (product);
CREATE INDEX IF NOT EXISTS ix_sales_transactions_category
    ON public.sales_transactions (category);
CREATE INDEX IF NOT EXISTS ix_sales_transactions_region
    ON public.sales_transactions (region);
CREATE INDEX IF NOT EXISTS ix_sales_transactions_sales_channel
    ON public.sales_transactions (sales_channel);
CREATE INDEX IF NOT EXISTS ix_sales_transactions_status
    ON public.sales_transactions (status);

CREATE OR REPLACE VIEW public.v_sales AS
SELECT
    transaction_id,
    order_date,
    date_trunc('month', order_date)::date AS order_month,
    product,
    category,
    region,
    sales_channel,
    quantity,
    unit_price,
    discount_amount,
    status,
    (quantity * unit_price)::numeric(14, 2) AS gross_sales,
    (quantity * unit_price - discount_amount)::numeric(14, 2) AS net_revenue,
    (status = 'completed') AS is_completed
FROM public.sales_transactions;

COMMENT ON VIEW public.v_sales IS
    'Centralized sales metrics: gross_sales, net_revenue, order_month, is_completed.';
