from nautobot.apps import jobs
from nautobot.dcim.models import Interface
from nautobot.ipam.models import Service
from pykeadhcp import Kea

name = "Kea related jobs"


class KeaSync(jobs.Job):
    class Meta:
        # metadata attributes go here
        name = "Sync Subnets and Hosts to Kea"

        def get_dhcp_servers(self):
            dhcp_servers = []
            dhcp_services = Service.objects.filter(protocol="udp", ports=[67])
            for dhcp_service in dhcp_services:
                interfaces = []
                for ip_address in dhcp_service.ip_addresses.all():
                    current_interface = Interface.objects.get(
                        ip_addresses=ip_address.id
                    )
                    interfaces.append(current_interface)
                dhcp_server = {
                    "dhcp_server": dhcp_service.device,
                    "interfaces": [],
                    "service": dhcp_service,
                }
                dhcp_servers.append(dhcp_server)
            return dhcp_servers

        def run(self):
            self.logger.info("Started a kea sync run")
            dhcp_servers = self.get_dhcp_servers()
            self.logger.info(f"Found the following DHCP servers: {dhcp_servers}")


jobs.register_jobs(KeaSync)
