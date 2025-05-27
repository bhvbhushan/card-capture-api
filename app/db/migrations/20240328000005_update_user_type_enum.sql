-- Drop existing enum type and recreate with new values
ALTER TABLE public.profiles 
    ALTER COLUMN role TYPE text;

DROP TYPE IF EXISTS public.user_type;

CREATE TYPE public.user_type AS ENUM ('admin', 'recruiter', 'reviewer', 'user');

-- Convert existing roles to the new enum type
UPDATE public.profiles 
SET role = 'user'::user_type 
WHERE role NOT IN ('admin', 'recruiter', 'reviewer', 'user');

-- Set the column type back to user_type
ALTER TABLE public.profiles 
    ALTER COLUMN role TYPE user_type USING role::user_type; 