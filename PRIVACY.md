# Privacy and voluntary contributions

Vacuum Water Monitor stores its settings, tank history, prospective declarations and
confirmed measurements locally in Home Assistant. Home Assistant backups include them.
The integration does not automatically send telemetry, measurements or diagnostics.

Optional sharing starts OFF, including installations with an older global opt-in.
Only saved confirmed physical measurements can create a contribution. The local preview
shows the exact packet. Separate consent changes its publication consent flag; the
subsequent download contains exactly the displayed JSON. Selecting another sample,
changing its saved data or turning sharing OFF clears that consent. The GitHub link opens
a blank maintained form. Downloading and opening the form do not upload data; the user
attaches the packet manually to publish it under CC BY 4.0.

The contribution projection includes technical model, retail and dock variants, firmware,
integration/version, reservoir, settings, area, measured water, instrument/resolution and
quality. It creates a random contribution identifier independent of local IDs. Household
and device IDs, user labels, names, accounts, tokens, absolute dates, MAC/IP addresses,
rooms, maps and raw private history are excluded. Unsupported free text becomes unknown.
Technical combinations can still indirectly identify a device, and GitHub exposes the
contributor account. This is minimization, not a guarantee of anonymity.

All contributions need maintainer review. An intake packet cannot become an approved
runtime rate on its own. Unknown context is accepted for review but does not establish
applicability or measured accuracy. Nominal capacity and empty anchors are estimates,
not physical measurements to publish as training truth.

Before publication, withdraw by turning sharing OFF and deleting the downloaded file.
After publication, request removal on the vacuum-consumption-data repository, identifying
the contribution UUID or issue. Maintainers can remove maintained records; public forks,
Git history, screenshots and other copies may remain. Changing a local setting cannot
revoke a published CC BY 4.0 licence or erase copies held elsewhere.

Integration Diagnostics are a separate local troubleshooting download and may contain
household information. Follow the sanitization instructions before sharing any report.
