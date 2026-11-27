-- Run in Supabase Dashboard > SQL Editor (project: media-pipeline). Idempotent. No destructive statements.
-- Model: browsers never touch tables or buckets directly. Only the backend (service_role key, which
-- bypasses RLS) reads/writes. Anonymous and authenticated roles get NO access.

alter table public.media_metadata enable row level security;

-- Explicit deny-by-default: no policies for anon/authenticated means no rows are visible.
revoke all on public.media_metadata from anon, authenticated;

-- The backend uses service_role: newer Supabase projects do not auto-grant table privileges, so grant explicitly.
grant usage on schema public to service_role;
grant select, insert, update, delete on public.media_metadata to service_role;

-- Keep updated_at honest even for manual edits.
create or replace function public.touch_updated_at() returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;
drop trigger if exists media_metadata_touch on public.media_metadata;
create trigger media_metadata_touch before update on public.media_metadata
  for each row execute function public.touch_updated_at();

-- Allowed status values and a lookup index for the worker queue.
do $$ begin
  alter table public.media_metadata add constraint media_metadata_status_chk
    check (status in ('UPLOADING','UPLOADED','PROCESSING','COMPLETED','FAILED'));
exception when duplicate_object then null; end $$;
create index if not exists media_metadata_status_idx on public.media_metadata (status, created_at);

-- Buckets stay private; make sure (idempotently) and cap size/types at the storage layer too.
update storage.buckets set public = false, file_size_limit = 52428800 where id in ('media-input','media-output');
-- storage.objects has RLS on by default. We add NO policies for anon/authenticated, so only
-- service_role (backend + worker) and signed URLs can reach objects.
