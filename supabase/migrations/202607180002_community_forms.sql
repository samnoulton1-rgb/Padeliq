create table if not exists public.contact_messages (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete set null,
  first_name text not null check (char_length(first_name) between 1 and 80),
  last_name text not null check (char_length(last_name) between 1 and 80),
  email text not null check (char_length(email) between 3 and 254),
  subject text not null check (char_length(subject) between 1 and 160),
  question text not null check (char_length(question) between 1 and 3000),
  source text not null default 'homepage',
  preferred_language text not null default 'en',
  status text not null default 'new',
  created_at timestamptz not null default now()
);

create table if not exists public.newsletter_subscribers (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  preferred_language text not null default 'en',
  source text not null default 'homepage',
  subscribed_at timestamptz not null default now(),
  unsubscribed_at timestamptz
);

create unique index if not exists newsletter_subscribers_email_idx
  on public.newsletter_subscribers (lower(email));
create index if not exists contact_messages_created_at_idx
  on public.contact_messages (created_at desc);

alter table public.contact_messages enable row level security;
alter table public.newsletter_subscribers enable row level security;

drop policy if exists "anyone_can_send_contact_message" on public.contact_messages;
create policy "anyone_can_send_contact_message"
  on public.contact_messages for insert to anon, authenticated
  with check (user_id is null or user_id = auth.uid());

drop policy if exists "anyone_can_join_newsletter" on public.newsletter_subscribers;
create policy "anyone_can_join_newsletter"
  on public.newsletter_subscribers for insert to anon, authenticated
  with check (unsubscribed_at is null);

comment on table public.contact_messages is 'Private inbound website enquiries. Public clients can insert but cannot read rows.';
comment on table public.newsletter_subscribers is 'Private email-list subscriptions. Public clients can insert but cannot read rows.';
