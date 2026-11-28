# Login outage on staging
Date: {{today}}
Event: Staging login failed for 2 hours because the IdP redirect URI lacked a trailing slash.
Impact: Redirect URIs must match the IdP registration exactly; added a check to the deploy script.
