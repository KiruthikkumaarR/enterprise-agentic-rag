# Incident Post-Mortems 2025

Blameless post-mortem summaries for major IT incidents at Halvorsen Industrial Systems.

## INC-2025-609: ERP order service outage

- **Date:** 2025-02-01
- **Severity:** SEV2
- **Duration:** 421 minutes
- **Root cause:** an expired TLS certificate
- **Corrective action owner:** Anna Etxeberria

The ERP order service was unavailable for 421 minutes. The root cause was an expired TLS certificate. Monitoring alerts were added and the runbook was updated.

## INC-2025-603: MES production scheduler outage

- **Date:** 2025-02-16
- **Severity:** SEV3
- **Duration:** 479 minutes
- **Root cause:** a full transaction-log disk
- **Corrective action owner:** Otto Wisniewski

The MES production scheduler was unavailable for 479 minutes. The root cause was a full transaction-log disk. Monitoring alerts were added and the runbook was updated.

## INC-2025-244: Customer portal outage

- **Date:** 2025-03-26
- **Severity:** SEV2
- **Duration:** 370 minutes
- **Root cause:** a misconfigured firewall rule
- **Corrective action owner:** Otto Costa

The Customer portal was unavailable for 370 minutes. The root cause was a misconfigured firewall rule. Monitoring alerts were added and the runbook was updated.

## INC-2025-960: VPN gateway outage

- **Date:** 2025-04-13
- **Severity:** SEV2
- **Duration:** 19 minutes
- **Root cause:** a faulty network switch firmware update
- **Corrective action owner:** Lukas Costa

The VPN gateway was unavailable for 19 minutes. The root cause was a faulty network switch firmware update. Monitoring alerts were added and the runbook was updated.

## INC-2025-222: Email relay outage

- **Date:** 2025-05-10
- **Severity:** SEV1
- **Duration:** 30 minutes
- **Root cause:** a database connection-pool leak
- **Corrective action owner:** Bruno Mendes

The Email relay was unavailable for 30 minutes. The root cause was a database connection-pool leak. Monitoring alerts were added and the runbook was updated.

## INC-2025-359: Warehouse scanner network outage

- **Date:** 2025-06-03
- **Severity:** SEV2
- **Duration:** 84 minutes
- **Root cause:** a DNS record deleted during cleanup
- **Corrective action owner:** Otto Lefevre

The Warehouse scanner network was unavailable for 84 minutes. The root cause was a DNS record deleted during cleanup. Monitoring alerts were added and the runbook was updated.

## INC-2025-178: Payroll batch outage

- **Date:** 2025-07-06
- **Severity:** SEV2
- **Duration:** 456 minutes
- **Root cause:** an unindexed query introduced in a release
- **Corrective action owner:** Aleksi Laine

The Payroll batch was unavailable for 456 minutes. The root cause was an unindexed query introduced in a release. Monitoring alerts were added and the runbook was updated.

## INC-2025-387: Pump telemetry ingestion outage

- **Date:** 2025-07-22
- **Severity:** SEV1
- **Duration:** 70 minutes
- **Root cause:** a power supply failure in rack B4
- **Corrective action owner:** Henrik Larsen

The Pump telemetry ingestion was unavailable for 70 minutes. The root cause was a power supply failure in rack B4. Monitoring alerts were added and the runbook was updated.

## INC-2025-750: Identity provider outage

- **Date:** 2025-08-15
- **Severity:** SEV1
- **Duration:** 273 minutes
- **Root cause:** a clock drift on the primary domain controller
- **Corrective action owner:** Claire Aguirre

The Identity provider was unavailable for 273 minutes. The root cause was a clock drift on the primary domain controller. Monitoring alerts were added and the runbook was updated.

## INC-2025-423: Backup cluster outage

- **Date:** 2025-09-15
- **Severity:** SEV1
- **Duration:** 400 minutes
- **Root cause:** an exhausted cloud API quota
- **Corrective action owner:** Joana Aguirre

The Backup cluster was unavailable for 400 minutes. The root cause was an exhausted cloud API quota. Monitoring alerts were added and the runbook was updated.
