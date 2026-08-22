# Model profile sources

Only manufacturer-published clean-water capacities are added as automatic
defaults. Usage rates remain unset when the manufacturer does not publish them;
users can add measured, device-scoped values through the card.

Other published facts are stored with explicit semantics. In particular,
laboratory maximum area per fill is not treated as average coverage or converted
to ml/m², and pre-task/mid-task wash volumes are not treated as a universal
wash-cycle volume.

| Canonical key | Recognised aliases | Verified profile facts | Sources |
| --- | --- | ---: | --- |
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

When adding another model:

1. Prefer a manufacturer product page, FAQ, or manual.
2. Record the exact HA/vendor identifier separately from the canonical name.
3. Add the capacity to both the Python and card databases.
4. Do not infer per-square-metre usage from tank capacity.
5. Add alias, unknown-model, and frontend smoke coverage before publishing.
6. Keep dock clean/dirty and robot clean/dirty tanks in distinct fields.
7. Keep pre-task, mid-task, and post-task wash volumes distinct; never use one
   as the generic accounting default unless the integration can classify the
   event reliably.
