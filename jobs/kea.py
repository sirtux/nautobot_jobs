import ipaddress

from nautobot.apps import jobs
from nautobot.dcim.models import Interface
from nautobot.extras.models import Relationship, RelationshipAssociation, Role
from nautobot.ipam.models import Service, Prefix, IPAddress
from pykeadhcp import Kea
import json

from social_django.urls import extra

name = "Kea related jobs"


class KeaSync(jobs.Job):
    class Meta:
        # metadata attributes go here
        name = "Sync DHCP Interfaces, Subnets and static hosts to Kea"

    def get_dhcp_servers(self):
        dhcp_servers = []
        dhcp_services = Service.objects.filter(protocol="udp", ports=[67])
        self.logger.debug(f"Found {len(dhcp_services)} dhcp services")
        for dhcp_service in dhcp_services:
            interfaces = []
            ip_addresses = dhcp_service.ip_addresses.all()
            self.logger.debug(f"Found {len(ip_addresses)} IP addresses")
            for ip_address in ip_addresses:
                current_interface = Interface.objects.get(ip_addresses=ip_address.id)
                interfaces.append(current_interface)
                self.logger.debug(
                    f"Identified {current_interface.name}",
                    extra={"object": current_interface},
                )
            self.logger.debug(f"Found {len(interfaces)} interfaces")
            dhcp_server = {
                "dhcp_server_device": dhcp_service.device,
                "interfaces": interfaces,
                "service": dhcp_service,
            }
            self.logger.debug(
                f"DHCP Server identified: {dhcp_server['dhcp_server_device'].name}",
                extra={"object": dhcp_server["dhcp_server_device"]},
            )
            dhcp_servers.append(dhcp_server)
        return dhcp_servers

    def configure_dhcp_server(self, dhcp_server):
        kea_secret = self.read_kea_secrets(dhcp_server)

        kea_uri = f"https://{dhcp_server['dhcp_server_device'].name}"
        kea_api = Kea(
            host=kea_uri,
            port=7777,
            username=kea_secret["user"],
            password=kea_secret["password"],
            use_basic_auth=True,
        )

        self.check_kea_connectivity(dhcp_server, kea_api)

        # Get the current configuration and remove the hash
        dhcp4_config = kea_api.dhcp4.config_get()
        dhcp4_config.arguments.pop("hash", None)
        dhcp6_config = kea_api.dhcp6.config_get()
        dhcp6_config.arguments.pop("hash", None)

        self.kea_add_interfaces_to_config(dhcp4_config, dhcp6_config, dhcp_server)

        # Subnets as loose objects

        # Find the subnets for this DHCP server and convert them to something usable.
        subnet_relationship = Relationship.objects.get(key="dhcp_server_to_subnet")
        subnets = RelationshipAssociation.objects.filter(
            relationship=subnet_relationship, source_id=dhcp_server["service"].id
        )

        self.logger.debug(
            f"Found {len(subnets)} subnets",
            extra={"object": dhcp_server["service"]},
        )

        kea_subnets_ipv4 = []
        kea_subnets_ipv6 = []

        self.kea_create_subnet_objects(
            dhcp_server, kea_subnets_ipv4, kea_subnets_ipv6, subnets
        )

        dhcp4_config.arguments["Dhcp4"]["subnet4"] = kea_subnets_ipv4
        dhcp6_config.arguments["Dhcp6"]["subnet6"] = kea_subnets_ipv6

        self.kea_send_and_save_config(dhcp4_config, dhcp6_config, dhcp_server, kea_api)

    def kea_create_subnet_objects(
        self, dhcp_server, kea_subnets_ipv4, kea_subnets_ipv6, subnets
    ):
        subnet_counter = 1
        for subnet in subnets:
            prefix = Prefix.objects.get(id=subnet.destination_id)
            resolved_prefix = self.resolve_prefix_details(prefix)
            self.logger.debug(
                f"Resolved prefix details: {resolved_prefix}", extra={"object": prefix}
            )

            # Begin configuring the subnet
            kea_subnet = {}
            kea_subnet["id"] = subnet_counter
            kea_subnet[
                "subnet"
            ] = f"{resolved_prefix['network']}/{resolved_prefix['prefix_length']}"

            # Build the option data parameter list
            option_data = []
            if len(resolved_prefix["dns"]) > 0:
                dns_servers = {
                    "data": ",".join(resolved_prefix["dns"]),
                    "name": "domain-name-servers",
                }
                option_data.append(dns_servers)
            if len(resolved_prefix["ntp"]) > 0:
                dns_servers = {
                    "data": ",".join(resolved_prefix["ntp"]),
                    "name": "ntp-servers",
                }
                option_data.append(dns_servers)
            if len(resolved_prefix["gateway"]) > 0:
                gateway = {
                    "data": ",".join(resolved_prefix["gateway"]),
                    "name": "routers",
                }
                option_data.append(gateway)

            kea_subnet["option-data"] = option_data
            subnet_pools = []
            for dhcp_pool in resolved_prefix["dhcp_pools"]:
                # If we define this as an CIDR, the network and broadcast will be used as well
                # Therefore, dark magic
                dhcp_pool_network = ipaddress.ip_network(dhcp_pool)
                subnet_pools.append(
                    {"pool": f"{dhcp_pool_network[1]} - {dhcp_pool_network[-2]}"}
                )
            kea_subnet["pools"] = subnet_pools

            if resolved_prefix["afi"] == 4 and (len(resolved_prefix["dhcp_pools"]) > 0):
                kea_subnets_ipv4.append(kea_subnet)
            if resolved_prefix["afi"] == 6 and (len(resolved_prefix["dhcp_pools"]) > 0):
                kea_subnets_ipv6.append(kea_subnet)

            self.logger.debug(
                f"Resolved IPv4 subnets: {kea_subnets_ipv4}",
                extra={"object": dhcp_server["service"]},
            )
            self.logger.debug(
                f"Resolved IPv6 subnets: {kea_subnets_ipv6}",
                extra={"object": dhcp_server["service"]},
            )
            subnet_counter += 1

    def kea_send_and_save_config(
        self, dhcp4_config, dhcp6_config, dhcp_server, kea_api
    ):
        self.logger.debug(
            "Calling config_set", extra={"object": dhcp_server["dhcp_server_device"]}
        )
        dhcp4_response = kea_api.dhcp4.config_set(dhcp4_config.arguments)
        dhcp6_response = kea_api.dhcp6.config_set(dhcp6_config.arguments)
        if dhcp4_response.result == 0:
            kea_api.dhcp4.config_write("/etc/kea/kea-dhcp4.conf")
            self.logger.info(
                "New DHCP4 Config successfully set",
                extra={"object": dhcp_server["dhcp_server_device"]},
            )
        else:
            self.logger.error(
                f"New DHCP4 Config failed: {dhcp4_response.text}",
                extra={"object": dhcp_server["dhcp_server_device"]},
            )
        if dhcp6_response.result == 0:
            kea_api.dhcp6.config_write("/etc/kea/kea-dhcp6.conf")
            self.logger.info(
                "New DHCP6 Config successfully set",
                extra={"object": dhcp_server["dhcp_server_device"]},
            )
        else:
            self.logger.error(
                f"New DHCP6 Config failed: {dhcp6_response.text}",
                extra={"object": dhcp_server["dhcp_server_device"]},
            )

    def kea_add_interfaces_to_config(self, dhcp4_config, dhcp6_config, dhcp_server):
        # Add the discovered interfaces
        dhcp_server_interface_names = []
        for dhcp_server_interfaces in dhcp_server["interfaces"]:
            dhcp_server_interface_names.append(dhcp_server_interfaces.name)
        # We need to remove duplicates, those happen if a device has multiple IP addresses
        dhcp_server_interface_names = list(set(dhcp_server_interface_names))
        self.logger.debug(
            f"Adding {dhcp_server_interface_names} to server config",
            extra={"object": dhcp_server["dhcp_server_device"]},
        )
        dhcp4_config.arguments["Dhcp4"]["interfaces-config"][
            "interfaces"
        ] = dhcp_server_interface_names
        dhcp6_config.arguments["Dhcp6"]["interfaces-config"][
            "interfaces"
        ] = dhcp_server_interface_names

    def read_kea_secrets(self, dhcp_server):
        self.logger.debug("Reading the secrets")
        with open("/opt/nautobot/secrets/kea.json", "r") as datafile:
            kea_secrets = json.load(datafile)
        try:
            kea_secret = next(
                item
                for item in kea_secrets
                if item["host"] == dhcp_server["dhcp_server_device"].name
            )
        except StopIteration:
            self.logger.error(
                "Secret not found for dhcp server",
                extra={"object": dhcp_server["dhcp_server_device"]},
            )
            raise NameError("Secret not found for dhcp server")
        except KeyError as e:
            self.logger.error(
                "host key not found",
                extra={"object": dhcp_server["dhcp_server_device"]},
            )
            raise e
        return kea_secret

    def check_kea_connectivity(self, dhcp_server, kea_api):
        try:
            kea_status = kea_api.ctrlagent.status_get()
            self.logger.debug(
                f"Connected to Kea Agent on PID {kea_status.pid}",
                extra={"object": dhcp_server["dhcp_server_device"]},
            )
        except Exception as e:
            self.logger.error(
                "Could not connect to Kea Agent",
                extra={"object": dhcp_server["dhcp_server_device"]},
            )
            raise e
        try:
            kea_status = kea_api.dhcp4.status_get()
            self.logger.debug(
                f"Connected to Kea DHCP4 on PID {kea_status.pid}",
                extra={"object": dhcp_server["dhcp_server_device"]},
            )
        except Exception as e:
            self.logger.error(
                "Could not connect to Kea DHCP4",
                extra={"object": dhcp_server["dhcp_server_device"]},
            )
            raise e
        try:
            kea_status = kea_api.dhcp6.status_get()
            self.logger.debug(
                f"Connected to Kea DHCP6 on PID {kea_status.pid}",
                extra={"object": dhcp_server["dhcp_server_device"]},
            )
        except Exception as e:
            self.logger.error(
                "Could not connect to Kea DHCP6",
                extra={"object": dhcp_server["dhcp_server_device"]},
            )
            raise e

    def resolve_service_ips_for_prefix(self, prefix, type):
        relationship = Relationship.objects.get(key=type)
        related_ip_addresses = RelationshipAssociation.objects.filter(
            relationship=relationship, destination_id=prefix.id
        )
        resolved_addresses = []
        for related_ip_address in related_ip_addresses:
            ip_address = IPAddress.objects.get(id=related_ip_address.source_id).host
            resolved_addresses.append(ip_address)

        if len(resolved_addresses) == 0:
            return []
        else:
            return resolved_addresses

    def resolve_prefix_details(self, prefix):
        gateway = self.resolve_service_ips_for_prefix(
            prefix=prefix, type="subnet_gateway"
        )
        dns = self.resolve_service_ips_for_prefix(
            prefix=prefix, type="dns_server_to_subnet"
        )
        ntp = self.resolve_service_ips_for_prefix(
            prefix=prefix, type="ntp_server_to_subnet"
        )
        dhcp_pool_role = Role.objects.get(name="dhcp-pool")
        dhcp_pool_prefixes = Prefix.objects.filter(
            role=dhcp_pool_role.id, parent_id=prefix.id
        )
        dhcp_pools = []
        for dhcp_pool_prefix in dhcp_pool_prefixes:
            dhcp_pools.append(
                f"{dhcp_pool_prefix.network}/{dhcp_pool_prefix.prefix_length}"
            )
        return {
            "afi": prefix.ip_version,
            "network": prefix.network,
            "prefix_length": prefix.prefix_length,
            "gateway": gateway,
            "dns": dns,
            "ntp": ntp,
            "dhcp_pools": dhcp_pools,
        }

    def run(self):
        self.logger.info("Started a kea sync run")
        dhcp_servers = self.get_dhcp_servers()
        self.logger.info(f"Found {len(dhcp_servers)} dhcp servers")
        for dhcp_server in dhcp_servers:
            self.configure_dhcp_server(dhcp_server)


jobs.register_jobs(KeaSync)
