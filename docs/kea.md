# Kea Config Generation from Nautobot

## Requirements / Basics

1. This script looks for DHCP servers by requesting services with UDP/67, and uses those hosts
as DHCP servers. IP Addresses must be configured in the service, however, it uses the underlying
interfaces in the configuration, not the IP addresses.

2. It will connect on port 7777 using the fqdn of the host, we have the full "primary" fqdn as
device name, auth data is read from /opt/nautobot/dhcp_auth.json.

3. dhcp_auth.json is a list of dicts, schema: ``[{"host1": {"user": "username", "password": "the password"}}]``.
In this specific implementation, this is a k8s secret mounted into the containers.
