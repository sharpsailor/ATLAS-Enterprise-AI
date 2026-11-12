-- Atlas schema (PostgreSQL 13+, gen_random_uuid is built in). Idempotent.

create table if not exists documents (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       text not null,
    title           text not null,
    owner_sub       text not null,
    allowed_groups  text[] not null default '{}',
    s3_key          text not null unique,
    status          text not null default 'pending'
                    check (status in ('pending', 'processing', 'ready', 'failed', 'retired')),
    current_version int  not null default 1,
    chunk_count     int,
    error           text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);
create index if not exists documents_tenant_idx on documents (tenant_id, created_at desc);

create table if not exists chat_messages (
    id              bigserial primary key,
    tenant_id       text not null,
    owner_sub       text not null,
    conversation_id uuid not null,
    role            text not null check (role in ('user', 'assistant')),
    content         text not null,
    created_at      timestamptz not null default now()
);
create index if not exists chat_messages_conv_idx on chat_messages (tenant_id, owner_sub, conversation_id, id);

create table if not exists approvals (
    id          uuid primary key default gen_random_uuid(),
    tenant_id   text not null,
    requester   text not null,
    question    text not null,
    status      text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
    reviewer    text,
    reviewed_at timestamptz,
    created_at  timestamptz not null default now()
);

create table if not exists feedback (
    id          bigserial primary key,
    tenant_id   text not null,
    actor       text not null,
    document_id uuid references documents (id) on delete set null,
    rating      int not null check (rating between -1 and 1),
    note        text not null default '',
    created_at  timestamptz not null default now()
);

create table if not exists audit_events (
    id         bigserial primary key,
    actor      text not null,
    tenant_id  text not null,
    action     text not null,
    detail     jsonb not null default '{}',
    created_at timestamptz not null default now()
);
create index if not exists audit_events_action_idx on audit_events (tenant_id, action);
