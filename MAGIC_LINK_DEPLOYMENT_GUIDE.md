# Magic Link System Deployment Guide

## Overview

This guide covers the deployment of the Magic Link system, which provides Outlook-compatible authentication links using query parameters instead of hash fragments.

## ✨ Features

- **🔗 Outlook Compatible**: Uses query parameters instead of hash fragments
- **🔐 Secure**: 32-character cryptographically secure tokens
- **⏰ Time-Limited**: 24-hour expiration window
- **🔄 Single-Use**: Tokens are consumed after first use
- **📧 Dual Purpose**: Supports both password resets and invitations
- **🗄️ Database Tracked**: All magic links stored in `magic_links` table

## 🏗️ Architecture

### Backend Components

1. **Database Table**: `magic_links`
   - Stores tokens, metadata, expiration times
   - Tracks usage and prevents replay attacks

2. **Repository Layer**: `app/repositories/auth_repository.py`
   - `create_magic_link_db()` - Generate secure tokens
   - `validate_magic_link_db()` - Check token validity
   - `consume_magic_link_db()` - Mark tokens as used
   - `send_magic_link_email_db()` - Send emails with magic links

3. **Service Layer**: `app/services/auth_service.py`
   - `validate_magic_link_service()` - Business logic for validation
   - `consume_magic_link_service()` - Handle token consumption and session creation

4. **API Endpoints**: `app/api/routes/auth.py`
   - `GET /auth/magic-link/validate` - Validate tokens
   - `POST /auth/magic-link/consume` - Process magic links

### Frontend Components

1. **Magic Link Page**: `src/pages/MagicLinkPage.tsx`
   - Handles magic link processing
   - Validates and consumes tokens
   - Redirects to appropriate pages

2. **API Integration**: `src/api/backend/users.ts`
   - `validateMagicLink()` - Call validation endpoint
   - `consumeMagicLink()` - Call consumption endpoint

3. **Routing**: Added `/magic-link` route to `App.tsx`

## 🚀 Deployment Steps

### 1. Database Setup

The `magic_links` table should already be created in both staging and production:

```sql
CREATE TABLE magic_links (
  id SERIAL PRIMARY KEY,
  token VARCHAR(255) UNIQUE NOT NULL,
  email VARCHAR(255) NOT NULL,
  type VARCHAR(50) NOT NULL CHECK (type IN ('password_reset', 'invite')),
  metadata JSONB DEFAULT '{}',
  expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
  used BOOLEAN DEFAULT FALSE,
  used_at TIMESTAMP WITH TIME ZONE NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Add indexes for performance
CREATE INDEX idx_magic_links_token ON magic_links(token);
CREATE INDEX idx_magic_links_email_type ON magic_links(email, type);
CREATE INDEX idx_magic_links_expires_at ON magic_links(expires_at);
```

### 2. Environment Variables

Ensure these environment variables are set:

```bash
# Required
FRONTEND_URL=https://cardcapture.io  # or staging URL
ENVIRONMENT=production              # or staging

# Supabase credentials (should already exist)
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
```

### 3. Backend Deployment

The backend changes are already implemented:

- ✅ Magic link repository functions
- ✅ Magic link service functions  
- ✅ Magic link API endpoints
- ✅ Updated invite and password reset functions

### 4. Frontend Deployment

The frontend changes are implemented:

- ✅ MagicLinkPage component
- ✅ Magic link API functions
- ✅ Updated routing

## 🧪 Testing

### Run the Test Script

```bash
python test_magic_links.py
```

This will test:
- Magic link creation and validation
- Token consumption and expiration
- API endpoint functionality
- URL generation

### Manual Testing

1. **Password Reset Test**:
   ```bash
   curl -X POST http://localhost:8000/auth/reset-password \
     -H "Content-Type: application/json" \
     -d '{"email": "test@example.com"}'
   ```

2. **Check Email**: Look for magic link URL like:
   ```
   https://cardcapture.io/magic-link?token=abc123...&type=password_reset
   ```

3. **Test Frontend**: Visit the magic link URL and verify:
   - Token validation works
   - Session is created
   - Redirect to appropriate page occurs

## 📧 Email Flow

### Password Reset Flow
1. User requests password reset
2. Backend creates magic link token
3. Email sent with: `https://cardcapture.io/magic-link?token=ABC&type=password_reset`
4. User clicks link (works in Outlook!)
5. Frontend validates token and creates session
6. User redirected to reset password page

### Invite Flow
1. Admin invites user
2. Backend creates magic link token with user metadata
3. Email sent with: `https://cardcapture.io/magic-link?token=XYZ&type=invite`
4. User clicks link
5. Frontend validates token and creates user account
6. User redirected to account setup page

## 🔧 Configuration

### Magic Link Settings

- **Token Length**: 32 characters (256 bits of entropy)
- **Expiration**: 24 hours from creation
- **Single Use**: Tokens are consumed after first use
- **Types**: `password_reset`, `invite`

### Outlook Compatibility

- ✅ Uses query parameters (not hash fragments)
- ✅ No JavaScript required for initial processing
- ✅ Works with corporate email security
- ✅ Handles email link scanning/pre-clicking

## 🔍 Monitoring

### Database Queries

Monitor magic link usage:

```sql
-- Check recent magic links
SELECT email, type, created_at, used, expires_at 
FROM magic_links 
WHERE created_at > NOW() - INTERVAL '1 day'
ORDER BY created_at DESC;

-- Check expired unused links
SELECT COUNT(*) as expired_unused
FROM magic_links 
WHERE expires_at < NOW() AND used = false;

-- Check usage patterns
SELECT type, COUNT(*) as total, 
       COUNT(CASE WHEN used THEN 1 END) as used_count
FROM magic_links 
GROUP BY type;
```

### Cleanup Task

Add to cron to clean old magic links:

```sql
DELETE FROM magic_links 
WHERE expires_at < NOW() - INTERVAL '7 days';
```

## 🚨 Troubleshooting

### Common Issues

1. **"Invalid or expired magic link"**
   - Check if token exists in database
   - Verify expiration time
   - Ensure token hasn't been used

2. **"Failed to create session"**
   - Check Supabase service role permissions
   - Verify user exists in auth.users table
   - Check network connectivity

3. **"Token not found"**
   - Verify token was created successfully
   - Check for typos in token parameter
   - Ensure URL encoding is correct

### Debug Commands

```bash
# Check magic link in database
python -c "
from app.core.clients import supabase_client
from app.repositories.auth_repository import validate_magic_link_db
result = validate_magic_link_db(supabase_client, 'YOUR_TOKEN_HERE')
print(result)
"

# Test token creation
python -c "
from app.core.clients import supabase_client
from app.repositories.auth_repository import create_magic_link_db
token = create_magic_link_db(supabase_client, 'test@example.com', 'password_reset')
print(f'Token: {token}')
"
```

## 📋 Checklist

- [ ] Database table `magic_links` exists in both staging and production
- [ ] Environment variables are set correctly
- [ ] Backend API endpoints respond correctly
- [ ] Frontend magic link page loads and processes tokens
- [ ] Email templates include magic link URLs
- [ ] Test script passes all tests
- [ ] Manual testing with real emails works
- [ ] Monitoring queries are set up
- [ ] Cleanup task is scheduled

## 🎯 Next Steps

1. **Production Testing**: Test with real email addresses
2. **Monitoring Setup**: Add logging and metrics
3. **Email Templates**: Update email templates if needed
4. **Documentation**: Update user-facing documentation
5. **Training**: Brief support team on new system

## 📞 Support

If you encounter issues:
1. Check the test script output
2. Review backend logs for error messages
3. Verify database table structure
4. Test API endpoints directly
5. Check environment variables

The magic link system is designed to be robust and Outlook-compatible, providing a better user experience for password resets and invitations. 