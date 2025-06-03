-- Create a trigger function that will call the Edge function
create or replace function handle_processing_jobs_insert()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  -- Call the Edge function using HTTP POST
  perform
    net.http_post(
      url := 'http://127.0.0.1:54321/functions/v1/process-job-trigger',
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

-- Create the trigger that fires after INSERT on processing_jobs table
create trigger processing_jobs_insert_trigger
  after insert on processing_jobs
  for each row execute function handle_processing_jobs_insert();

-- Grant necessary permissions
grant usage on schema net to authenticated, anon;
grant execute on function handle_processing_jobs_insert() to authenticated, anon; 