# Model profile sources

Only manufacturer-published clean-water capacities are treated as verified
capacity defaults. Manufacturers generally do not publish ml/m², so usage data is
kept in a separate evidence layer: `maintainer_estimate`, `cross_model_estimate`,
or `not_published`. Estimated rates always carry uncertainty and can be corrected
per device; they are never presented as manufacturer measurements.

At runtime, the backend resolves the profile from the Home Assistant device registry and
returns its canonical `profile_key`, source/confidence, tracked reservoir/capacity,
distinct reservoirs, capability, evidence and only same-device signal roles. The card
uses those fields as authoritative. Its older browser catalog is a compatibility fallback
only when an older backend response has no descriptor. Capacity alone never authorizes an
automatic usage estimate: `manual_only` profiles require a measured calibration/manual
refill baseline. Profiles with labelled empirical ml/m² seeds may derive a bounded
active-time rate using 0.8 m²/min when an integration lacks area; this starts at no less
than 65% uncertainty and the conversion is user-editable.

Other published facts are stored with explicit semantics. In particular,
laboratory maximum area per fill is not treated as average coverage or converted
to ml/m², and pre-task/mid-task wash volumes are not treated as a universal
wash-cycle volume.

| Canonical key | Recognised aliases | Verified profile facts | Sources |
| --- | --- | ---: | --- |
| `roborock_s8_maxv_ultra` | `a97`, `roborock.vacuum.a97` | Dock clean 4000 ml; robot clean 100 ml; VibraRise 3.0 sonic mop and edge mop | [Roborock comparison](https://support.roborock.com/hc/en-us/articles/33954114436761-What-is-the-difference-among-of-S8-Pro-Ultra-S8-Max-Ultra-and-S8-MaxV-Ultra), [Roborock feature page](https://support.roborock.com/hc/en-us/articles/33954061643673-What-s-the-key-features-of-S8-MaxV-Ultra) |
| `roborock_qrevo_5ae` | `a170`, `roborock.vacuum.a170`, `roborock_q_revo_5ae` | Dock 4000/3500 ml; robot clean 80 ml; max 200 rpm; max 10 mm lift; 30 flow levels; three-stage wash; 45°C drying air | [Roborock Singapore specifications](https://www.roborock.sg/products/roborock-qrevo-5ae-white-certified-refurbished), [Roborock Malaysia product page](https://my.roborock.com/pages/roborock-qrevo-5ae) |
| `roborock_qrevo_curv_2_flow` | `a245`, `roborock.vacuum.a245`, FlowX name variants | Dock clean ~4000 ml; robot dirty ~100 ml; max 220 rpm; max 15 N; max 15 mm lift; continuous fresh-water roller | [Roborock South Korea FAQ](https://kr.roborock.com/blogs/roborock-kr/qrevo-curv-2-flow-faq), [global product page](https://global.roborock.com/pages/roborock-qrevo-curv-2-flow), [Roborock support](https://help.roborock.com/en-CA/product/qrevo-curv-2-flow-message?category=troubleshooting-1-1-1) |
| `xiaomi_h50` | canonical product-name slug | Dock 4000/4000 ml; tested max 240 m²/fill; max 180 rpm; three flow levels; max 10 mm lift | [Xiaomi H50 product page](https://www.mi.com/global/product/xiaomi-robot-vacuum-h50/) |
| `xiaomi_h50_pro` | `xiaomi_robot_vacuum_h50_pro` | Dock 4000/4000 ml; tested max 240 m²/fill; max 180 rpm; max 10 mm lift; pre-task 180 ml; mid-task 120 ml; 5/8/10 m² or minute intervals | [Xiaomi H50 Pro product page](https://www.mi.com/global/product/xiaomi-robot-vacuum-h50-pro/), [Xiaomi H50 Pro FAQ](https://www.mi.com/global/support/faq/details/KA-673648/) |
| `tapo_rv50_pro_omni` | `tapo_rv50_pro` | Dock 5000/4000 ml; robot clean 95 ml; three flow levels; 60°C wash; 50°C drying; dirt detection; automatic detergent | [Tapo RV50 Pro Omni specifications](https://www.tapo.com/us/product/robot-vacuum/tapo-rv50-pro-omni/) |

`a170` is the model identifier reported by a user in issue #5; it is not stated
on the manufacturer product page. `a245` is the model
parameter in the [official Roborock app deep link](https://app.roborock.com/d?model=a245)
printed in the Qrevo Curv 2 Flow/FlowX manual. FlowX is listed as a variant of
the same product family on [Roborock's official German product page](https://de.roborock.com/pages/roborock-qrevo-curv-2-flow).

## Integration signal contracts

Adapter mappings use Home Assistant `translation_key`, documented vacuum attributes or
Valetudo's canonical MQTT discovery names. Localized display labels and arbitrary entity
name substrings are not accounting inputs. The maintained status/sensor/unit matrix and
fail-closed behaviour are documented in
[Integration signal contracts](integration-signal-contracts.md).

- [Home Assistant Roborock](https://www.home-assistant.io/integrations/roborock/)
- [Home Assistant Ecovacs](https://www.home-assistant.io/integrations/ecovacs/)
- [Home Assistant Xiaomi Miio](https://www.home-assistant.io/integrations/xiaomi_miio/)
- [Home Assistant Roomba/Braava](https://www.home-assistant.io/integrations/roomba/)
- [Home Assistant Matter RVC source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/matter/vacuum.py)
- [Home Assistant SmartThings](https://www.home-assistant.io/integrations/smartthings/)
- [Home Assistant TP-Link source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/tplink/sensor.py)
- [Valetudo MQTT](https://valetudo.cloud/pages/integrations/mqtt/)
- [Dreame Vacuum entity reference](https://github.com/Tasshack/dreame-vacuum/blob/master/docs/entities.md)

When adding another model:

1. Prefer a manufacturer product page, FAQ, or manual.
2. Record the exact HA/vendor identifier separately from the canonical name.
3. Add the capacity to the canonical JSON catalog and regenerate the card fallback.
4. Do not infer per-square-metre usage from tank capacity.
5. If empirical usage seeds are added, label their evidence and uncertainty; never cite a
   capacity page as proof of ml/m².
6. Add alias, unknown-model, adapter and frontend smoke coverage before publishing.
7. Keep dock clean/dirty and robot clean/dirty tanks in distinct fields.
8. Keep pre-task, mid-task, and post-task wash volumes distinct; never use one
   as the generic accounting default unless the integration can classify the
   event reliably.
9. Bind a profile's rate axis to the signal the integration actually exposes:
   mop route, water intensity/spray, or cleaning mode are not interchangeable.
   Ranged number controls must be normalized from their own HA min/max.
