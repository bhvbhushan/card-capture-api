# Setting Up Supabase Storage for Email Assets

## 1. Create Assets Bucket

```sql
-- Create a public bucket for email assets
INSERT INTO storage.buckets (id, name, public)
VALUES ('email-assets', 'email-assets', true);
```

## 2. Set Public Access Policy

```sql
-- Allow public read access to email assets
CREATE POLICY "Public read access for email assets" ON storage.objects
FOR SELECT USING (bucket_id = 'email-assets');

-- Allow authenticated users to upload assets (optional)
CREATE POLICY "Authenticated upload for email assets" ON storage.objects
FOR INSERT WITH CHECK (
  bucket_id = 'email-assets' 
  AND auth.role() = 'authenticated'
);
```

## 3. Upload Logo Files

Upload these files to the `email-assets` bucket:
- `cc-logo-text-transparent.png`
- `cc-logo-only.svg` (as fallback)

## 4. Get Public URLs

After upload, your URLs will be:
```
https://[your-project].supabase.co/storage/v1/object/public/email-assets/cc-logo-text-transparent.png
https://[your-project].supabase.co/storage/v1/object/public/email-assets/cc-logo-only.svg
```

## 5. Update Email Template

Replace the image src in the email template:
```html
<img src="https://[your-project].supabase.co/storage/v1/object/public/email-assets/cc-logo-text-transparent.png" alt="Card Capture" />
```

## 6. Test Image Access

Visit the URL in your browser to confirm it loads properly. 