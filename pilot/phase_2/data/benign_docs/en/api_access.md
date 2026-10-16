---
title: API access
---
# API access

## Who can use the API
API access is included in the Pro and Enterprise plans. Admins can create keys from Settings, Developers.

## Creating a key
Give each key a name that says what it is for, such as the inventory sync. The full key is shown only once, so copy it to a safe place.

## Rotating keys
Create a new key, update your integration, then delete the old key. We recommend rotating keys every few months and whenever a team member leaves.

## Rate limits
Each key has a limit on requests per minute. If you exceed it, the API returns a rate-limit response and you should retry after a short wait.

## Webhooks
Webhooks send order and payment events to your server. Each request is signed so your server can check that it came from us.

## Developer support
Questions about the API go to the developer support form on the Developers page. Include the request time and the error you received.
