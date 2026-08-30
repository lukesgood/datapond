"""The sample dataset's relationships hold, by test rather than by assertion.

The point of this data is that things join. A demo where orders reference customers
that do not exist teaches the relationship graph to draw an edge with nothing behind
it, and teaches whoever is looking that the product is lying to them.

The dataset was inline in the sample-db route, which is where it stopped being
checkable — five tables of DDL and INSERT text inside a request handler.
"""
from app.sample_data import (
    DATASET,
    JOIN_QUERIES,
    KNOWLEDGE_SOURCES,
    foreign_keys,
    insert_statement,
    table,
    table_names,
)


def test_the_dataset_covers_more_than_one_domain():
    """A single domain has nothing to join across, which is the whole exercise."""
    assert len(DATASET) >= 12
    assert {t.domain for t in DATASET} >= {"commerce", "support", "logistics", "marketing"}


def test_every_table_name_is_unique():
    names = table_names()
    assert len(names) == len(set(names))


def test_every_foreign_key_points_at_a_table_in_the_dataset():
    names = set(table_names())
    for fk in foreign_keys():
        assert fk.parent in names, f"{fk.child}.{fk.column} references missing {fk.parent}"


def test_every_foreign_key_points_at_a_column_that_exists():
    for fk in foreign_keys():
        assert fk.parent_column in table(fk.parent).columns, (
            f"{fk.child}.{fk.column} references {fk.parent}.{fk.parent_column}, "
            f"which is not a column of {fk.parent}")


def test_every_foreign_key_value_in_the_seed_resolves():
    """Referential integrity of the generated rows, not just of the schema.

    Postgres would catch this on insert, but only on a machine with Postgres — and by
    then the failure is a 500 from a demo endpoint rather than a red test.
    """
    for fk in foreign_keys():
        parent_values = {row[fk.parent_column] for row in table(fk.parent).rows}
        for row in table(fk.child).rows:
            value = row.get(fk.column)
            if value is None:
                continue
            assert value in parent_values, (
                f"{fk.child}.{fk.column} = {value!r} has no {fk.parent} to point at")


def test_the_domains_are_joined_to_each_other_not_only_within_themselves():
    """Three self-contained islands would look like variety and behave like one table.

    Every added domain has to reach back into commerce, or the relationship graph shows
    disconnected clusters and no query spans them.
    """
    cross = {(table(fk.child).domain, table(fk.parent).domain) for fk in foreign_keys()}
    for domain in ("support", "logistics", "marketing"):
        assert any(a == domain and b != domain for a, b in cross), (
            f"{domain} joins nothing outside itself")


def test_every_row_has_exactly_the_declared_columns():
    for t in DATASET:
        for row in t.rows:
            assert set(row) == set(t.columns), f"{t.name} row shape differs: {row}"


def test_every_table_carries_rows():
    for t in DATASET:
        assert t.rows, f"{t.name} is empty — an empty table draws no edge"


# ── generated SQL ─────────────────────────────────────────────────────────────

def test_the_insert_names_its_columns():
    """Positional inserts break the moment a column is added in the middle."""
    sql, args = insert_statement(table("customers"))
    assert "INSERT INTO customers (" in sql
    for column in table("customers").columns:
        assert column in sql


def test_the_insert_binds_values_rather_than_interpolating_them():
    sql, args = insert_statement(table("customers"))
    assert "$1" in sql
    assert len(args) == len(table("customers").rows) * len(table("customers").columns)


def test_a_value_containing_a_quote_is_not_interpolated_into_the_sql():
    """Seed text is prose — Korean support tickets contain apostrophes."""
    sql, _args = insert_statement(table("ticket_messages"))
    assert "'" not in sql


# ── the queries that make edges observed ──────────────────────────────────────

def test_the_join_queries_only_reference_tables_in_the_dataset():
    """These run after the sync to put real joins in query_history, which is the only
    thing that makes a relationship graph edge solid rather than a naming guess."""
    names = set(table_names())
    for query in JOIN_QUERIES:
        for referenced in query.tables:
            assert referenced in names, f"{query.name} references unknown {referenced}"


def test_every_join_query_actually_joins():
    for query in JOIN_QUERIES:
        assert len(query.tables) >= 2, f"{query.name} touches one table"
        assert "join" in query.sql.lower()


def test_the_join_queries_cover_every_cross_domain_relationship():
    """An edge nobody queries stays dashed. If the point is a populated graph, the
    queries have to reach every join the schema declares across domains."""
    cross = {(fk.child, fk.parent) for fk in foreign_keys()
             if table(fk.child).domain != table(fk.parent).domain}
    covered = {pair for q in JOIN_QUERIES
               for pair in ((a, b) for a in q.tables for b in q.tables)}
    missing = [pair for pair in cross if pair not in covered and pair[::-1] not in covered]
    assert not missing, f"no query joins {missing}"


# ── knowledge ─────────────────────────────────────────────────────────────────

def test_knowledge_sources_point_at_real_columns():
    """A collection ingesting a column that does not exist fails at ingest time, in
    front of whoever is being shown the product."""
    for source in KNOWLEDGE_SOURCES:
        assert source.table in table_names(), f"{source.collection} → missing {source.table}"
        assert source.column in table(source.table).columns, (
            f"{source.collection} → {source.table}.{source.column} does not exist")


def test_knowledge_draws_on_more_than_one_domain():
    assert len({table(s.table).domain for s in KNOWLEDGE_SOURCES}) >= 2


def test_the_ingested_columns_hold_prose_rather_than_identifiers():
    """Embedding a column of SKUs produces a collection that retrieves nothing useful.
    A minimum length is a crude test for prose, and crude is enough to catch a column
    chosen by name."""
    for source in KNOWLEDGE_SOURCES:
        values = [row[source.column] for row in table(source.table).rows]
        longest = max(len(str(v or "")) for v in values)
        assert longest >= 40, f"{source.table}.{source.column} is not prose ({longest} chars)"


def test_the_sequences_are_reset_after_explicit_ids():
    """Rows carry explicit ids so foreign keys can be checked before anything is
    inserted. That leaves every SERIAL sequence at 1, and the next real insert
    collides on the primary key."""
    from app.sample_data import sequence_reset_statements

    statements = sequence_reset_statements()
    assert statements
    assert all("setval" in s for s in statements)


def test_the_ddl_is_generated_from_the_declared_columns():
    """Hand-written DDL beside a column list is two truths that drift. The first
    symptom is an insert naming a column the table does not have."""
    from app.sample_data import ddl_statement

    sql = ddl_statement(table("shipments"))
    assert sql.startswith("CREATE TABLE IF NOT EXISTS shipments")
    for column in table("shipments").columns:
        assert column in sql
    assert "REFERENCES orders(id)" in sql


def test_existing_tables_gain_new_columns_rather_than_being_left_behind():
    """CREATE TABLE IF NOT EXISTS does nothing to a table that already exists, so a
    deployment seeded before a column was added never gets it — and the insert then
    fails on the column that is missing."""
    from app.sample_data import column_backfill_statements

    statements = column_backfill_statements()
    joined = "\n".join(statements)
    assert "ADD COLUMN IF NOT EXISTS" in joined
    assert "products" in joined and "description" in joined


def test_seeding_the_sample_database_requires_a_write_permission():
    """The route runs CREATE DATABASE and registers a connector.

    The connectors router carries require_user_or_internal, which is authentication,
    not authorization — so the route-inventory test passed it while any logged-in
    account, `viewer` included, could create a database. Every other route that
    creates a connector holds connector:write.
    """
    import main

    route = next(r for r in main.app.routes
                 if getattr(r, "path", "") == "/api/connectors/sample-db")
    markers = [getattr(d.call, "__datapond_authorization__", None)
               for d in route.dependant.dependencies]
    assert "connector:write" in markers, f"markers on the route: {markers}"


# ── activation: making the loaded data visible ────────────────────────────────
# Seeding PostgreSQL is half the job. The tables reach the catalog through a connector
# sync; the relationship graph draws solid edges only from joins in query_history; and
# Knowledge shows a source only once a collection has ingested one. Each step depends
# on the one before, and each can be half-done, so the plan is data and is checked.

def test_the_activation_plan_runs_the_steps_in_the_only_order_that_works():
    from app.sample_data import activation_steps

    steps = [s.key for s in activation_steps()]
    assert steps.index("sync") < steps.index("queries"), (
        "the join queries read catalog tables, which the sync creates")
    assert steps.index("sync") < steps.index("knowledge"), (
        "ingest reads a catalog column, which the sync creates")


def test_every_activation_step_says_what_it_needs_first():
    from app.sample_data import activation_steps

    for step in activation_steps():
        assert step.requires is None or step.requires in {s.key for s in activation_steps()}


def test_the_knowledge_step_carries_one_request_per_collection():
    from app.sample_data import knowledge_ingest_requests

    requests = knowledge_ingest_requests()
    assert len(requests) == len(KNOWLEDGE_SOURCES)
    for request, source in zip(requests, KNOWLEDGE_SOURCES):
        assert request["collection"] == source.collection
        assert request["source"]["table"] == source.table
        assert request["source"]["text_column"] == source.column


def test_the_ingest_request_names_the_schema_the_sync_writes_into():
    """A collection pointed at the wrong schema ingests nothing and reports success."""
    from app.sample_data import CATALOG_SCHEMA, knowledge_ingest_requests

    for request in knowledge_ingest_requests():
        assert request["source"]["schema"] == CATALOG_SCHEMA
        assert request["source"]["type"] == "iceberg"


def test_the_join_queries_are_qualified_for_the_catalog_not_for_postgres():
    """They ran against sampledb when seeded; they run against the catalog afterwards,
    and an unqualified name resolves to whatever the engine's default schema is."""
    from app.sample_data import CATALOG_SCHEMA, catalog_join_queries

    for query in catalog_join_queries():
        for referenced in query.tables:
            assert f"{CATALOG_SCHEMA}.{referenced}" in query.sql, (
                f"{query.name} leaves {referenced} unqualified")


def test_qualifying_does_not_disturb_the_aliases():
    """`FROM support_tickets t` must become `FROM <schema>.support_tickets t` — losing
    the alias breaks every column reference in the statement."""
    from app.sample_data import catalog_join_queries

    query = next(q for q in catalog_join_queries() if q.name == "tickets_by_customer_tier")
    assert " t JOIN " in query.sql or " t\nJOIN " in query.sql
    assert "t.customer_id = c.id" in query.sql


def test_qualifying_leaves_result_column_names_alone():
    from app.sample_data import catalog_join_queries

    for query in catalog_join_queries():
        assert " AS " in query.sql or " as " in query.sql


# ── seeding into a database that is not empty ─────────────────────────────────
# Live, first run: "Key (customer_id)=(29) is not present in table customers".
#
# The tests above proved the dataset's own integrity, which held. What broke was
# seeding *into an existing one*: the route skipped any table that already had rows,
# so `customers` kept ten rows from an older seed while `support_tickets`, empty,
# received rows referencing forty. Per-table skipping cannot preserve a constraint
# that spans tables.

def test_parents_are_seeded_before_the_rows_that_reference_them():
    """Insert order is the only thing making a foreign key satisfiable mid-run.

    It happened to be right. Nothing said so, and appending a table in the wrong place
    would have failed at the database rather than here.
    """
    seen = set()
    for t in DATASET:
        for fk in t.references:
            assert fk.parent in seen or fk.parent == t.name, (
                f"{t.name} is seeded before {fk.parent}, which it references")
        seen.add(t.name)


def test_the_insert_tolerates_rows_that_are_already_there():
    """Every table is inserted on every run — a table is never skipped for having
    rows, because skipping one and not another is what broke the constraint between
    them. Conflicts are the expected case, not an error."""
    for t in DATASET:
        sql, _args = insert_statement(t)
        assert "ON CONFLICT DO NOTHING" in sql, t.name
