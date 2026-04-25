# 09 超售 / 换房 / Walk SOP

#### 关键词
`超售 / Overbooking / Walk / Relocation / 换酒店 / 换房 / 升级 / Upgrade / 降级 / Downgrade / DBR / Denied Boarding / OOO / 房态 / Inventory`

## 1. 超售机制与原因

### 1.1 为什么超售存在

- **No-Show 率 ≈ 5–8%**（高峰期 + 商务酒店）
- **早离 / Early Departure ≈ 2–5%**
- 收益管理预测取消率，故意超售 1–10% 来填补空房

### 1.2 超售种类

| 类型 | 触发原因 |
| --- | --- |
| 客观超售 | 渠道库存同步失败、PMS 与 OTA 不一致 |
| 主观超售 (Strategic) | RMS 故意超售 |
| 房型超售 | 某具体房型不足，可换其他房型 |
| 全酒店超售 | 整店满房 |

### 1.3 超售识别

差旅平台应在以下情形提前预警：

```
- T-72h 仍未发邮件确认入住 → 致电酒店再次确认
- T-24h 收到酒店"系统升级"通知 → 多数为超售前兆
- T-24h 酒店发"近期满房"邮件 → 极可能 Walk
- 入住当日酒店来电询问 ETA + 房型偏好 → 可能在筛选 Walk 客
- 入住时酒店"无你预订"且态度敷衍 → 已被 Walk
```

## 2. Walk 优先级（被酒店换出）

被 "Walk" 的客人，**酒店优先选**：

```
1. 一晚客 (1 晚 + 散客 + BAR)
2. 非品牌会员
3. OTA 预付（已收钱，矛盾较小）
4. 临柜 walk-in（无法事先抗议）
5. 未到酒店认识的常客
```

被酒店**优先保留**：

```
1. 长住客 (≥3 晚)
2. 高级会员（钛 / 钻石）
3. 直签销售 / 协议公司客
4. 本酒店常客 (Repeat Guest)
5. 客户接待 / VIP
```

## 3. Walk 标准补救

### 3.1 应当向酒店争取的标准

```
1. 同档或更高档的可比酒店（同星级、同区域、≤3km）
2. 第一晚酒店全免（含税）
3. 酒店之间双向交通（出租 / 专车）
4. 直拨长途话费报销
5. 公司一封正式致歉信
6. 礼宾经理 / Front Office Manager 当面致歉
7. 损失补偿券（如 50,000 集团积分 / 1 张免费房券）
8. 后续若回归本店，自动免费升级
```

### 3.2 高级会员 / 钻石卡 / 协议公司额外争取

- 同酒店内"升级套房"（如可用）
- 行政酒廊 / 早餐豁免
- 50,000–80,000 集团积分
- 集团客服 24h 内书面道歉
- 公司 RFP 续签时可作为谈判筹码

## 4. 出行人现场处理 SOP

### 4.1 现场流程

```
[1] 拒绝 immediately accept 第一份 Walk 方案
[2] 索取书面 Walk Notice（含 Walk 原因、被安排酒店、补偿）
[3] 联络 TMC（24/7 热线）
[4] TMC 协助：
       ├─ 联系集团客服 / 销售经理
       ├─ 协议公司可走"协议公司专属 Walk 流程"
       ├─ 高级会员走"礼宾接待"
[5] 若被安排酒店不可接受：
       ├─ 同档以上 + ≤3km：可接受
       ├─ 降档 / 远郊：拒绝并要求升级方案
[6] 入住替代酒店 → 索取替代酒店发票（用于报销）
[7] 原酒店退款 / 凭证留底
[8] 关单后填写客诉
```

### 4.2 被 Walk 后费用归属

| 项目 | 费用归属 |
| --- | --- |
| 替代酒店第 1 晚 | 原酒店承担 |
| 替代酒店后续晚 | 视协议（通常按原酒店原价收，差额由原酒店补） |
| 单程出租 | 原酒店承担 |
| 双程出租（往返） | 原酒店承担 |
| 长途话费 | 原酒店承担 |
| 出行人时间损失 | 不可索赔（除特殊场景） |
| 心理 / 重大不便 | 仅在协议公司、VIP 时通过补偿券 |

## 5. 升级 / 降级

### 5.1 升级 (Upgrade)

| 情形 | 处理 |
| --- | --- |
| 酒店主动升级（同价升档） | 出行人接受、不影响差标 |
| 出行人现场要求升级（自费） | 视差旅政策（多数禁自费升级） |
| 套房升级（高级会员） | 接受，但仍按原价开发票 |
| 行政房升级 | 接受 |

> **风险**：酒店可能"升级"但仍按"协议价"出账；离店时账单显示"升级费 RMB 500"，差旅系统应在离店前后比对，避免员工被动签单。

### 5.2 降级 (Downgrade)

| 情形 | 处理 |
| --- | --- |
| 房型超售，酒店主动降级 | 必须退差价 |
| 客人接受降级 + 酒店补偿 | 接受补偿（早餐 / 积分） |

## 6. 换房 (Room Change)

### 6.1 出行人发起

| 原因 | 是否合规 |
| --- | --- |
| 噪音 / 异味 / 故障 | 合规，免费换 |
| 楼层 / 朝向不满意 | 视酒店（多数免费一次） |
| 想升级 | 不合规 / 自费 |

### 6.2 酒店发起

| 原因 | 处理 |
| --- | --- |
| 工程维修 (OOO) | 必须换，免费 |
| 安全事件 | 必须换，免费 + 补偿 |
| VIP 接待挪房 | 必须经客人同意 + 补偿 |

## 7. 系统字段建议

```yaml
overbooking_event:
  detected_at: timestamp
  detection_signal: pre_arrival_call|on_arrival|no_inventory_in_pms|other
  walked: bool
  walk_to_hotel: string
  walk_to_distance_km: number
  walk_compensation_amount: number
  walk_compensation_currency: CNY
  walk_compensation_components:
    - type: first_night_waived|transport|long_distance_call|points|cert|other
      amount: number
  customer_satisfaction_after_walk: 1-5
upgrade_event:
  upgraded_to_room_type: string
  surcharge: number (0 = 免费)
  initiator: hotel|guest|system
downgrade_event:
  downgraded_to_room_type: string
  refund_amount: number
  refund_status: pending|paid|disputed
```

## 8. 风险点

1. **酒店"假超售"**：实际有房但希望换给更高价客户（如团体）；差旅平台应记录酒店年度 Walk 次数 / Walk Rate，纳入 RFP
2. **OTA 预付被 Walk**：OTA 仅退原酒店金额，未必覆盖替代酒店差价；差旅系统应在 Merchant 模式 Walk 时主动垫付差价并向 OTA 主张
3. **凌晨被 Walk**：出行人体验最差，建议高级会员 / 客户接待场景全部走"双 confirm"
4. **Walk 后无书面凭证**：未来报销 / 申诉无法主张，必须索取 Walk Notice
5. **协议公司 Walk Rate**：年度 RFP 应含"≤X% Walk Rate"条款，违反时酒店赔偿协议金 / 失去协议价资格
6. **敏感人群被 Walk**：孕妇 / 老人 / 残障 / 外宾，差旅平台需主动设置"高优先级保护标签"

## 9. 防御策略

```
[采购] RFP 时签订"Walk SLA"
[出单] 协议价 / 月结优先
[T-72h] 自动复核确认号有效
[T-24h] 高级会员客户主动联络酒店
[当日 14:00] 给酒店打电话确认
[当日 16:00] 仍无房 → 内部启动 Walk 应急
[当日 18:00] 多酒店同时 Walk → 内部预案
```

## 10. 与其他章节的关系

- 客诉补救：[15_complaint_handling_sop.md](15_complaint_handling_sop.md)
- 协议价 / RFP：[10_corporate_rate_contract_sop.md](10_corporate_rate_contract_sop.md)
- 不可抗力：[16_force_majeure_sop.md](16_force_majeure_sop.md)
- 渠道差异：[05_distribution_channels.md](05_distribution_channels.md)
