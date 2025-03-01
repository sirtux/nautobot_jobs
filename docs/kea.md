# Kea Config Generation from Nautobot

## Requirements / Basics

1. This script looks for DHCP servers by requesting services with UDP/67, and uses those hosts
as DHCP servers. IP Addresses must be configured in the service, however, it uses the underlying
interfaces in the configuration, not the IP addresses.

2. It will connect on port 7777 using the fqdn of the host, we have the full "primary" fqdn as
device name, auth data is read from /opt/nautobot/secrets/kea.json.

3. kea.json is a list of dicts, schema: ``[{"host1": {"user": "username", "password": "the password"}}]``.
In this specific implementation, this is a k8s secret mounted into the containers.

4. To assign subnets to a DHCP service, we use a relationship, which is specified as follows:
```json
{
      "object_type": "extras.relationship",
      "display": "DHCP Server to Subnet",
      "natural_slug": "dhcp-server-to-subnet_afa7",
      "source_type": "ipam.service",
      "destination_type": "ipam.prefix",
      "label": "DHCP Server to Subnet",
      "key": "dhcp_server_to_subnet",
      "description": "",
      "type": "one-to-many",
      "required_on": "",
      "source_label": "DHCP Subnets",
      "source_hidden": false,
      "source_filter": null,
      "destination_label": "DHCP Server",
      "destination_hidden": false,
      "destination_filter": null,
      "advanced_ui": false
    }
```
5. We use the same approach to connect DNS and NTP servers and the gateway IP to the subnets, the relationships are the following:
- DNS
```json
{
      "object_type": "extras.relationship",
      "display": "DNS Server to Subnet",
      "natural_slug": "dns-server-to-subnet_c996",
      "source_type": "ipam.ipaddress",
      "destination_type": "ipam.prefix",
      "label": "DNS Server to Subnet",
      "key": "dns_server_to_subnet",
      "description": "",
      "type": "many-to-many",
      "required_on": "",
      "source_label": "DNS for Subnets",
      "source_hidden": false,
      "source_filter": null,
      "destination_label": "Assigned DNS Server",
      "destination_hidden": false,
      "destination_filter": null,
      "advanced_ui": false
    }
```
- NTP
 ```json
{
      "object_type": "extras.relationship",
      "display": "NTP Server to Subnet",
      "natural_slug": "ntp-server-to-subnet",
      "source_type": "ipam.ipaddress",
      "destination_type": "ipam.prefix",
      "label": "DNS Server to Subnet",
      "key": "ntp_server_to_subnet",
      "description": "",
      "type": "many-to-many",
      "required_on": "",
      "source_label": "NTP for Subnets",
      "source_hidden": false,
      "source_filter": null,
      "destination_label": "Assigned NTP Server",
      "destination_hidden": false,
      "destination_filter": null,
      "advanced_ui": false
    }
```
- Gateway
 ```json
{
    "object_type": "extras.relationship",
    "display": "Subnet Gateway",
    "natural_slug": "subnet-gateway_2fa0",
    "source_type": "ipam.prefix",
    "destination_type": "ipam.ipaddress",
    "label": "Subnet Gateway",
    "key": "subnet_gateway",
    "description": "",
    "type": "one-to-one",
    "required_on": "",
    "source_label": "Gateway",
    "source_hidden": false,
    "source_filter": null,
    "destination_label": "Gateway for",
    "destination_hidden": false,
    "destination_filter": null,
    "advanced_ui": false,
    }
```
6. DHCP Pools
To assign a pool to a subnet, just create a pool within that subnet, and assign it the role "dhcp-pool".
In this implementation, only full CIDR pools are supported.
