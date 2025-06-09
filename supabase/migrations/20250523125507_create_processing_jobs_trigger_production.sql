-- Update the trigger function to use production Edge function URL
-- Replace 'YOUR_SUPABASE_PROJECT_REF' with your actual Supabase project reference
create or replace function handle_processing_jobs_insert()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  -- Call the Edge function using HTTP POST
  -- In production, replace the URL with your actual Supabase project URL:
  -- 'https://YOUR_SUPABASE_PROJECT_REF.supabase.co/functions/v1/process-job-trigger'
  perform
    net.http_post(
      url := case 
        when current_setting('app.environment', true) = 'production' then
          'https://YOUR_SUPABASE_PROJECT_REF.supabase.co/functions/v1/process-job-trigger'
        else
          'http://127.0.0.1:54321/functions/v1/process-job-trigger'
      end,
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'Authorization', 'Bearer ' || current_setting('app.settings.service_role_key', true)
      ),
      body := jsonb_build_object(
        'record', to_jsonb(NEW)
      )
    );
  
  return NEW;
end;
$$; 