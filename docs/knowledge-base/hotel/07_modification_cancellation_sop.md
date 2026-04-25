# 07 改签 / 取消 / 退款 SOP

#### 关键词
`改签 / 修改 / 取消 / 退款 / 退订 / NRF / Non-Refundable / FRD / 全退 / 部分退 / 违约金 / 违约 / 罚款 / no-show / 早离 / 担保 / 信用卡 / 时差 / 时区 / 协议价 / OTA 政策`

## 1. 总体决策表

```
入住前 [ X 小时 ] → 决定退款 / 改签是否产生费用
                  ↓
按 rate_plan.cancel_policy 字段计算
                  ↓
匹配 ↓ 决策路径 ↓
```

| 政策类型 | 改签 | 取消 | 处罚 |
| --- | --- | --- | --- |
| Refundable + 24h Free | 任意改 | 入住前 ≥24h 全退 | 0 |
| Refundable + 48h Free | 任意改 | 入住前 ≥48h 全退 | 0 |
| Refundable + 72h Free | 任意改 | 入住前 ≥72h 全退 | 0 |
| Semi-Refundable | 改签免罚 | 入住前 ≥X h 50% 退 | 50% |
| Non-Refundable | 不可改 | 不可退 | 100% |
| Group Rate | 取消含阶梯 | 取消含阶梯 | 阶梯式 |

## 2. 时区与"小时"定义

| 锚点定义 | 含义 | 举例 |
| --- | --- | --- |
| Local Hotel Time | 酒店当地时间 | 国际酒店通用 |
| Guest Local Time | 出行人当地时间 | 极少用 |
| 24:00 (UTC+8) | 入住前一日酒店当地 24:00 | 国内多数 |

> 若 OTA 显示"入住前 24 小时免费取消"，但具体酒店写着"入住当日中午 12:00 前免费"，**以 OTA 实际下单时合同条款为准**。差旅平台应在订单明细持久化 `cancel_deadline_local`（含时区）。

## 3. 取消处理流程

```
[1] 客户发起取消
       ↓
[2] 系统计算距离 cancel_deadline_local 的剩余秒数
       ↓
[3] 调用渠道取消 API
       ↓
[4] 等待返回:
        ├─ HX/Cancelled: 直接退款 / 释放预授权
        ├─ Pending: 异步处理，T+5 分钟内复核
        └─ Failed: 进入人工工单
       ↓
[5] 财务流程: 触发退款 / 月结冲销
       ↓
[6] 通知出行人、主管、酒店
       ↓
[7] 关单
```

### 3.1 取消渠道差异

| 渠道 | 取消方式 | 注意 |
| --- | --- | --- |
| 集团直连 | API + 集团确认号 | 通常实时返回 |
| GDS | XX/HX 段，PNR 修改 | TMC 操作 |
| OTA Agency 模式 | OTA 后台或 API | 酒店端同步 |
| OTA Merchant 模式 | OTA 退款 → OTA 通知酒店 | 客户已付，OTA 退还客户 |
| 批发商 | 批发商 API | 取消时间窗口可能更严 |
| 酒店直签 | 邮件 + 销售经理确认 | 留存邮件凭证 |

## 4. 改签处理流程

### 4.1 改签 vs 取消重订

| 场景 | 推荐做法 |
| --- | --- |
| 同酒店、同房型、改日期且仍在免费窗口 | 改签 |
| 同酒店、同日期、改房型 | 改签（若渠道支持） |
| 跨酒店 / 跨城市 | 取消 + 重订 |
| 入住人变更 | 视协议（部分酒店允许免费换名，部分要求重订） |

### 4.2 改签可能产生的费用

```
ΔRate     = 新价 − 原价
Cancel Fee = 视改签策略
Total Diff = ΔRate + Cancel Fee
```

某些渠道改签 = 取消旧 + 创建新订单：

- 旧订单按取消政策计费
- 新订单按当下 BAR / 协议价
- 差旅系统应模拟两种路径，给客户最优建议

## 5. 退款时效

| 渠道 / 支付方式 | 退款时效 | 备注 |
| --- | --- | --- |
| 国内信用卡 (Visa/Master/JCB) | 7–15 工作日 | 跨境结算 |
| 国内 UnionPay 借记卡 | 1–3 工作日 |  |
| 微信支付 | 0–24h | 即时 |
| 支付宝 | 0–24h | 即时 |
| 公司 BTA / Lodge Card | 月结对账时冲销 | 不退现 |
| Direct Bill (月结挂账) | 月结对账时冲销 |  |
| 海外信用卡 | 5–30 工作日 |  |
| 海外 ACH / Bank Transfer | 30 工作日 |  |
| 现金 / Walk-in | 入店退现 |  |

## 6. 不可退订单的处置

### 6.1 主要思路

```
1. 重新利用：能否改签到本人未来行程
2. 转售：能否在公司内部转给其他出行人
3. 申诉：渠道 / 集团酒店是否能 Goodwill 退款
4. 合规损失：写入差旅政策"不可退订单需主管审批"
```

### 6.2 Goodwill 退款话术（应用模板）

> "尊敬的客户经理，我司员工 [姓名] 因突发 [合规事由：医疗、防疫、签证拒签、紧急公务]，无法按期入住贵酒店预订（确认号 [XXXX]）。现请您协助申请 goodwill 退款 / 改签。我方愿意在贵酒店未来 [N 个月] 内重新预订作为补偿。"

### 6.3 申诉成功的常见前提

- 不可抗力：自然灾害、疫情管控、政府限行、签证拒签
- 健康事由：住院、隔离
- 公务变更：客户取消接待、紧急任务调动
- 同集团忠诚客户：金 / 钛 / 钻石卡可申请 1–2 次年度豁免
- 协议公司：年度合同允许 ≤X% 取消率，可走"协议豁免池"

## 7. 取消违约金计算细节

### 7.1 含税 vs 不含税

| 行情 | 多数集团 | 多数 OTA | 国内 |
| --- | --- | --- | --- |
| 罚金基数 | 房价（不含税） | 含税总价 | 含税总价 |
| 罚金税务处理 | 视赔偿性 / 服务性 | 视协议 | 视发票 |

> 国内：违约金通常**不开发票**（属赔偿金），但部分酒店开"违约金"普票或 zero-VAT 收据。

### 7.2 阶梯计算示例

```
原订单：3 晚，3,000 / 晚 + 6% VAT = 9,540 总
取消政策：
  ≥72h 免费
  72h > X ≥ 24h 收 1 晚 = 3,180
  < 24h 收全程 = 9,540
  No-Show 收全程 = 9,540
```

## 8. 部分取消（Partial Cancel）

| 场景 | 处理 |
| --- | --- |
| 取消其中 1 晚（缩短住宿） | 部分取消（多数酒店允许，但需在免费窗口内） |
| 缩短至 2 晚但已过 cancel deadline | 早离 (Early Departure)，按早离政策 |
| 多间房单笔订单取消其中 1 间 | 多数渠道支持，部分 OTA 不支持单间取消 |

差旅系统应原生支持"按间-按晚"的部分取消。

## 9. 修改入住人

| 场景 | 处理 |
| --- | --- |
| 同部门同公司换人 | 直连 / TMC 多数允许免费换名 |
| 跨公司换人 | 视为新订单（重订） |
| 多人订单中 1 人不来 | 仅取消该入住人，房费视协议（多人入住价 vs 单人价差） |

## 10. 分类决策表（详细）

### 10.1 国内渠道

| 渠道 | 免费取消窗口 | 改签窗口 | 不可退提醒 |
| --- | --- | --- | --- |
| 携程"立即确认 + 免费取消" | 入住前一日 18:00 前免费 | 同 | 卡片显示 |
| 携程"促销不可退" | 不可退 | 不可改 | 强提示 |
| 美团"免费取消" | 入住前 6:00 前 | 同 | 卡片显示 |
| 美团"特惠 / 闪购" | 不可退 | 不可改 | 强提示 |
| 飞猪信用住 | 入住前任意时刻免费 | 入住前一日 | 信用住一般可退 |
| 直连华住 | 入住当日 18:00 前免费 | 同 | 视酒店 |
| 直连锦江 / 维也纳 | 入住当日 18:00 前免费 | 同 | 视酒店 |
| 直连香格里拉 | 入住前 24h | 同 |  |

### 10.2 海外渠道

| 渠道 | 免费取消窗口 | 改签窗口 |
| --- | --- | --- |
| Marriott BAR | 入住前 24–72h（视酒店） | 同 |
| Hilton Best Available | 入住前 24–48h | 同 |
| Hyatt Daily Rate | 入住前 24–72h | 同 |
| IHG Flexible | 入住前 4–24h | 同 |
| Accor Flexible | 入住前 4–24h | 同 |
| Booking.com Free Cancel | 视酒店（24h–7 日） | 同 |
| Expedia Refundable | 视酒店 |  |
| Agoda Free Cancel | 视酒店 |  |
| Hotelbeds | 视具体酒店（多数 NRF） |  |

## 11. 系统字段建议

```yaml
cancel_policy:
  refundable: true|false
  free_cancel_until_local: "2026-04-30T18:00:00+08:00"
  cancel_tiers:
    - until_local: "2026-04-30T18:00:00+08:00"
      fee_amount: 0
      fee_currency: "CNY"
      fee_pct_of_first_night: 0
    - until_local: "2026-05-01T14:00:00+08:00"
      fee_amount: 580
      fee_currency: "CNY"
      fee_pct_of_first_night: 100
    - until_local: "INFINITY"
      fee_amount_full_stay: true
  noshow_policy:
    fee_amount_full_stay: true
  early_departure_policy:
    fee_amount_first_night: true
modify_policy:
  modifiable: true|false
  modifications_require_recheck: true
```

## 12. 风险点

1. **客户在 cancel deadline 后 5 分钟内取消**：系统实际请求时间 ≤ 截止时间，但渠道侧时差 / 时钟漂移导致拒绝 → 立刻调取我方系统时间戳证据
2. **OTA 显示免费但酒店端已扣**：常见于 Merchant 模式同步延迟，差旅平台需按 OTA 协议向 OTA 主张
3. **跨日期订单中跨过 cancel deadline**：例如订 5 月 1–3 日，5 月 1 日 09:00 取消，多数协议视为 No-Show 收全程
4. **节假日 / 高峰期酒店变更政策**：节前 1 周可能升级为不可退，差旅系统在订单层快照 `cancel_policy_at_booking_time`
5. **货币汇率波动**：罚金按 USD 计，退款按 RMB 退，员工对损失敏感 → 主动告知"以入住时酒店实际扣款币种为准"

## 13. 与其他章节的关系

- 渠道差异：[05_distribution_channels.md](05_distribution_channels.md)
- 价格码：[04_rate_plans_and_fees.md](04_rate_plans_and_fees.md)
- No-Show / 早离：[08_noshow_earlycheckout_latecheckin_sop.md](08_noshow_earlycheckout_latecheckin_sop.md)
- 客诉申诉：[15_complaint_handling_sop.md](15_complaint_handling_sop.md)
- 不可抗力豁免：[16_force_majeure_sop.md](16_force_majeure_sop.md)
