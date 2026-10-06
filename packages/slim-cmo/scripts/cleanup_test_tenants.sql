-- Cleanup of CMO test residue left in the DEV database by two interrupted test runs.
-- REVIEW BEFORE RUNNING. Run as the table owner (metrion_migrate) or a superuser, e.g.:
--   docker exec -i metrion-postgres-1 psql -U metrion -d metrion < packages/slim-cmo/scripts/cleanup_test_tenants.sql
--
-- PART 1 is read-only (previews). PART 2 deletes, inside ONE transaction, and ABORTS (nothing
-- deleted) unless the guard checks pass. It touches ONLY:
--   * CMO rows of exactly these two tenants (both business_name = 'Test Tenant'):
--       b035b3be-5d87-4674-9b5e-46e3c7a52dd2
--       cf5b1b3c-0436-4b7c-85b0-8261ce081bcf
--   * format_constraint rows with row_kind = 'TEST_FIXTURE' that no remaining CMO row references.
-- It does NOT touch: the real tenant ("Zyquora", 012028f0-...), the tenant rows themselves,
-- vision_eval_run (see note), any non-CMO table, any VERIFIED format_constraint row.

\echo '=== PART 1: PREVIEW (read-only) ==='

\echo '-- 1a. tenants that will be targeted (expect exactly 2, both "Test Tenant")'
select id, clerk_org_id, business_name, created_at from tenant
 where id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2', 'cf5b1b3c-0436-4b7c-85b0-8261ce081bcf');

\echo '-- 1b. every tenant named "Test Tenant" (must be the same 2 ids)'
select id from tenant where business_name = 'Test Tenant';

\echo '-- 1c. CMO rows that will be deleted, per table'
select 'cmo_title_approval' t, count(*) from cmo_title_approval where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf')
union all select 'cmo_title_option', count(*) from cmo_title_option where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf')
union all select 'cmo_trend_report', count(*) from cmo_trend_report where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf')
union all select 'seller_fact', count(*) from seller_fact where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf')
union all select 'cmo_niche_term', count(*) from cmo_niche_term where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf')
union all select 'cmo_quota_reservation', count(*) from cmo_quota_reservation where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf')
union all select 'cmo_generation', count(*) from cmo_generation where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf')
union all select 'product_image_analysis', count(*) from product_image_analysis where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf')
union all select 'seller_image_asset', count(*) from seller_image_asset where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf')
union all select 'cmo_platform_config (NOT deleted, shown for info)', count(*) from cmo_platform_config where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf');

\echo '-- 1d. CMO rows belonging to ANY OTHER tenant (expect all zeros: nothing real is at risk)'
select 'cmo_generation' t, count(*) from cmo_generation where tenant_id not in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf')
union all select 'seller_image_asset', count(*) from seller_image_asset where tenant_id not in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf')
union all select 'product_image_analysis', count(*) from product_image_analysis where tenant_id not in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf')
union all select 'seller_fact', count(*) from seller_fact where tenant_id not in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf');

\echo '-- 1e. format_constraint rows: by kind, and TEST_FIXTURE rows still referenced by a generation of another tenant (expect 0)'
select row_kind, count(*) from format_constraint group by row_kind;
select count(*) as fixture_rows_referenced_by_other_tenants from format_constraint f
 where f.row_kind = 'TEST_FIXTURE'
   and exists (select 1 from cmo_generation g where g.format_constraint_ref = f.id
               and g.tenant_id not in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf'));

\echo '-- 1f. foreign keys that constrain the delete order (live catalog)'
select conrelid::regclass as child, confrelid::regclass as parent, conname, condeferrable as deferrable
  from pg_constraint
 where contype = 'f'
   and (conrelid::regclass::text in ('cmo_generation','cmo_title_option','cmo_title_approval','cmo_trend_report','seller_fact','product_image_analysis','cmo_niche_term','cmo_quota_reservation')
        or confrelid::regclass::text = 'format_constraint')
 order by 1, 2;

\echo '-- 1g. NOTE: vision_eval_run (platform table, no tenant_id) row count; NOT touched by this script'
select count(*) as vision_eval_run_rows from vision_eval_run;

\echo '=== PART 2: GUARDED DELETE (one transaction; any guard failure aborts with nothing deleted) ==='
begin;
set constraints all deferred;

do $guard$
declare n int; m int; other int;
begin
  select count(*) into n from tenant
   where id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf')
     and business_name = 'Test Tenant' and clerk_org_id = 'org_' || id::text;
  select count(*) into m from tenant where business_name = 'Test Tenant';
  select (select count(*) from cmo_generation where tenant_id not in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf'))
       + (select count(*) from seller_image_asset where tenant_id not in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf'))
       + (select count(*) from product_image_analysis where tenant_id not in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf'))
       into other;
  if n <> 2 or m <> 2 then raise exception 'GUARD: expected exactly the 2 named Test Tenant rows (found % / %); nothing deleted', n, m; end if;
  if other <> 0 then raise exception 'GUARD: % CMO rows belong to other tenants; nothing deleted', other; end if;
end
$guard$;

delete from cmo_title_approval     where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf');
delete from cmo_title_option       where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf');
delete from cmo_trend_report       where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf');
delete from seller_fact            where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf');
delete from cmo_niche_term         where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf');
delete from cmo_quota_reservation  where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf');
delete from cmo_generation         where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf');
delete from product_image_analysis where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf');
delete from seller_image_asset     where tenant_id in ('b035b3be-5d87-4674-9b5e-46e3c7a52dd2','cf5b1b3c-0436-4b7c-85b0-8261ce081bcf');

-- TEST_FIXTURE constraint rows: only those no remaining generation references (FK would refuse anyway).
delete from format_constraint f
 where f.row_kind = 'TEST_FIXTURE'
   and not exists (select 1 from cmo_generation g where g.format_constraint_ref = f.id);

\echo '-- post-delete check inside the transaction (expect zeros), then commit'
select (select count(*) from cmo_generation) as generations_left,
       (select count(*) from format_constraint where row_kind = 'TEST_FIXTURE') as test_fixture_left;
commit;
