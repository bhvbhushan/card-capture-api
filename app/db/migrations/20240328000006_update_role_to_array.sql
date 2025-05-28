-- First, convert the role column to text[] to store multiple roles
ALTER TABLE public.profiles 
    ALTER COLUMN role TYPE text[] USING ARRAY[role::text];

-- Update the default value to be an array
ALTER TABLE public.profiles 
    ALTER COLUMN role SET DEFAULT ARRAY['user'];

-- Update the handle_new_user trigger function to handle role arrays
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
declare
  v_school_id uuid;
  v_roles text[];
begin
  -- Debug logging
  raise log 'Creating new user profile with metadata:';
  raise log 'raw_user_meta_data: %', new.raw_user_meta_data;
  raise log 'raw_app_meta_data: %', new.raw_app_meta_data;
  
  -- Try to get school_id from both metadata sources
  v_school_id := (new.raw_user_meta_data->>'school_id')::uuid;
  if v_school_id is null then
    v_school_id := (new.raw_app_meta_data->>'school_id')::uuid;
  end if;
  
  -- Get roles from metadata, defaulting to ['user'] if not present
  v_roles := coalesce(
    (new.raw_user_meta_data->>'role')::text[],
    ARRAY['user']
  );
  
  raise log 'Extracted school_id: %', v_school_id;
  raise log 'Extracted roles: %', v_roles;
  
  insert into public.profiles (
    id,
    email,
    first_name,
    last_name,
    role,
    school_id
  )
  values (
    new.id,
    new.email,
    (new.raw_user_meta_data->>'first_name')::text,
    (new.raw_user_meta_data->>'last_name')::text,
    v_roles,
    v_school_id
  );
  return new;
end;
$$;

-- Update RLS policies to check for role arrays
DROP POLICY IF EXISTS "profiles_admin_update" ON public.profiles;
CREATE POLICY "profiles_admin_update"
    ON public.profiles
    FOR UPDATE
    TO authenticated
    USING (
        EXISTS (
            SELECT 1 
            FROM public.profiles 
            WHERE id = auth.uid() 
            AND 'admin' = ANY(role)
        )
    );

-- Update the is_admin function to work with role arrays
CREATE OR REPLACE FUNCTION public.is_admin(user_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
begin
    return exists (
        select 1 from profiles
        where id = user_id
        and 'admin' = ANY(role)
    );
end;
$$; 