# 宽表字段说明

> **字段名以视图 / 宽表 `daily_with_maindata`（及 `v_daily_with_maindata`）实际 SELECT 输出为准**；源表文档仅作中文解释与备注参考。  
> 下列第一章、第二章分别对应视图中来自日K、来自 `lc_maindatanew` 的字段；顺序与视图一致。

## 一、日K字段（来源：`last_5years_daily`，视图别名 `d`）

| 字段名 | 中文解释 | 备注 |
|--------|----------|------|
| market_code | 数据来源（SH:上海交易所、SZ:深证交易所、BJ:北京交易所、GZ：股转） | 视图字段，与日K表同名 |
| category | 行情类别（指数:index、股票:stock、基金:fund、债券:bond、其他:other） | |
| code | 股票代码 | 与 secumain.SecuCode 关联键 |
| timestamps | 时间戳 | as-of 交易日 |
| open | 开盘价 | |
| close | 收盘价 | |
| high | 最高价 | |
| low | 最低价 | |
| ycp | 昨收价 | |
| vol | 成交量 | |
| amount | 成交额 | |
| ChangePCT | 涨跌幅(%) | |
| RangePCT | 振幅(%) | |
| TurnoverRate | 换手率(%) | |
| Ifsuspend | 是否停牌 | |
| if_up | 是否上涨 | |
| if_flat | 是否平盘 | |
| if_down | 是否下跌 | |
| RisingUpDays | 连涨天数 | |
| FallingDownDays | 连跌天数 | |
| MaxRisingUpDays | 历史连涨最多天数 | |
| MaxFallingDownDays | 历史连跌最多天数 | |
| FallOnDebut | 是否破发 | |
| FallOnNAPS | 是否破净 | |
| StockBoard | 今日是否涨停一字板 | |
| LimitBoard | 今日是否跌停一字板 | |
| SurgedLimit | 今日是否涨停股 | |
| DeclineLimit | 今日是否跌停股 | |
| HighestPrice | 今日是否创历史新高 | |
| LowestPrice | 今日是否创历史新低 | |
| HighestPriceRW | 是否近一周新高 | |
| LowestPriceRW | 是否近一周新低 | |
| HighestPriceTW | 是否本周以来新高 | |
| LowestPriceTW | 是否本周以来新低 | |
| HighestPriceRM | 是否近一月新高 | |
| LowestPriceRM | 是否近一月新低 | |
| HighestPriceTM | 是否本月以来新高 | |
| LowestPriceTM | 是否本月以来新低 | |
| HighestPriceRMThree | 是否近三个月新高 | |
| LowestPriceRMThree | 是否近三个月新低 | |
| HighestPriceRMSix | 是否近半年新高 | |
| LowestPriceRMSix | 是否近半年新低 | |
| HighestPriceRY | 是否近一年新高 | |
| LowestPriceRY | 是否近一年新低 | |
| HighestPriceYTD | 是否今年以来新高 | |
| LowestPriceYTD | 是否今年以来新低 | |
| ema12 | EMA12 | |
| ema26 | EMA26 | |
| dif | DIF | |
| dea | DEA | |
| macd | MACD | |
| max_high_9 | 9日最高价 | |
| min_low_9 | 9日最低价 | |
| RSV | RSV | |
| kdj_k | KDJ-K | |
| kdj_d | KDJ-D | |
| kdj_j | KDJ-J | |
| ma5 | 5日均线 | |
| ma20 | 20日均线 | |
| ma_signal | 均线信号 | |
| macd_signal | MACD信号 | |
| kdj_signal | KDJ信号 | |
| strategy | 策略1 | |
| ma4 | 4日均线 | |
| ma8 | 8日均线 | |
| ma12 | 12日均线 | |
| ma16 | 16日均线 | |
| ma47 | 47日均线 | |

## 二、财务主数据字段（来源：`lc_maindatanew`，视图别名 `f`）

> 仅列出**已写入视图**的字段；源表中的 `ID`、`UpdateTime`、`JSID`、`InsertTime`、`NetOperateCashFlowPSRe` 等未进入视图，故不收录。  
> `CompanyCode` 在视图中来自 `secumain`（别名 `m`），不在本章重复。  
> 匹配规则：截至交易日最近一期（`EndDate` ≤ 当日）。

| 字段名 | 中文解释 | 备注 |
|--------|----------|------|
| InfoPublDate | 信息发布日期 | 同报告期多条时取最新披露 |
| InfoSource | 信息来源 | 优先展示披露「主要会计数据」模块的财报来源 |
| BulletinType | 公告类别 | 10-发行上市书，20-定期报告，30-业绩快报，70-临时公告 |
| EndDate | 截止日期 | as-of 匹配关键字段 |
| AccountingStandards | 会计准则 | 与 CT_SystemConst.DM 关联（LB=1455）：1-新会计准则(2007)，9-旧会计准则 |
| Mark | 合并调整标志 | 与 CT_SystemConst.DM 关联（LB=1188，DM IN 1,2,4,5,6,7,8）：1-是，2-否，4-否(7-9月)，5-是(7-9月)，6-一季末调整，7-二季末调整，8-三季末调整 |
| BasicEPS | 基本每股收益(元) | 新准则取实际披露数；旧准则取每股收益（加权） |
| DilutedEPS | 稀释每股收益(元) | |
| BasicEPSCut | 基本每股收益(扣除)(元) | |
| DilutedEPSCut | 稀释每股收益(扣除)(元) | |
| EPS | 每股收益(摊薄)(元) | 归母净利润 / 最新总股本 |
| ROEByReport | 净资产收益率(摊薄)-原始披露(%) | 展示原文披露值 |
| ROE | 净资产收益率(摊薄)(%) | 计算值：归母净利润 / 归母股东权益 |
| ROECut | 净资产收益率(摊薄-扣除)(%) | 优先原文；未披露则按扣非归母净利润/归母股东权益*100 计算 |
| WROE | 净资产收益率(加权)(%) | 展示原文披露值 |
| WROECut | 净资产收益率(加权-扣除)(%) | 展示原文披露值 |
| OperatingReenue | 营业收入(元) | 源表字段名拼写为 OperatingReenue（缺 v） |
| NPFromParentCompanyOwners | 净利润(不含少数损益)(元) | |
| NetProfitCut | 扣除非经常性损益后归母净利润(元) | |
| ProfitatISA | 国际会计准则净利润(元) | |
| MarginIntoOutStatement | 境内外审计净利润差异说明 | （废弃）2022-11-24起废弃 |
| RetainedProfit | 未分配利润(元) | |
| NetOperateCashFlow | 经营活动产生的现金流量净额(元) | |
| NetOperateCashFlowPS | 每股经营活动现金流量净额(元) | 优先原文；未披露则=经营现金流净额/期末总股本 |
| CashEquialentIncrease | 现金及现金等价物净增加额(元) | |
| CashEquialents | 货币资金(元) | |
| TotalAssets | 资产总计(元) | |
| SEWithoutMI | 股东权益(不含少数权益)(元) | |
| NetAssetISA | 国际会计准则净资产/股东权益(元) | |
| NAPSByReport | 每股净资产-原始披露(元) | 展示财报原文披露值 |
| NAPS | 每股净资产(元) | 优先原文；未披露则=(归母所有者权益-其他权益工具)/期末总股本 |
| NAPSAdjusted | 调整后每股净资产(元) | 历史披露字段，现已不再披露 |
| CapitalResereFund | 资本公积(元) | |
| TotalShares | 总股本(股) | |
| DiidendFinancing | 分配融资方案说明 | |
| TotalRecompense | 领导人报酬总额(元) | （废弃）2022-11-24起废弃 |
| FeeForAccountantOffice | 会计师事务所费用(元) | （废弃）2022-11-24起废弃 |
| OperatingProfit | 营业利润(元) | |
| TotalProfit | 利润总额(元) | |
| ModifiedAuditOpinion | 非标准审计意见描述 | （废弃）2022-11-24起废弃 |
| FairValueChangeIncome | 公允价值变动净收益(元) | |
| NonoperatingIncome | 营业外收入(元) | |
| NonoperatingExpense | 营业外支出(元) | |
| IncomeTaxCost | 所得税(元) | |
| UncertainedInvestmentLosses | 未确认的投资损失(元) | |
| MinorityProfit | 少数股东损益(元) | |
| NetProfit | 净利润(元) | |
| NetInvestCashFlow | 投资活动产生的现金流量净额(元) | |
| NetFinanceCashFlow | 筹资活动产生的现金流量净额(元) | |
| ExchanRateChangeEffect | 汇率变动对现金及现金等价物的影响 | |
| EndPeriodCashEquivalent | 期末现金及现金等价物余额 | |
| TradingAssets | 交易性金融资产(元) | |
| InterestReceivables | 应收利息(元) | |
| DividendReceivables | 应收股利(元) | |
| AccountReceivables | 应收账款(元) | |
| OtherReceivable | 其他应收款(元) | |
| Inventories | 存货(元) | |
| TotalCurrentAssets | 流动资产合计(元) | |
| HoldForSaleAssets | 可供出售金融资产(元) | |
| HoldToMaturityInvestments | 持有至到期投资(元) | |
| InvestmentProperty | 投资性房地产(元) | |
| LongtermEquityInvest | 长期股权投资(元) | |
| IntangibleAssets | 无形资产(元) | |
| TotalNonCurrentAssets | 非流动资产合计(元) | |
| ShortTermLoan | 短期借款(元) | |
| TradingLiability | 交易性金融负债(元) | |
| SalariesPayable | 应付职工薪酬(元) | |
| DividendPayable | 应付股利(元) | |
| TaxsPayable | 应交税费(元) | |
| InterestPayable | 应付利息(元) | |
| OtherPayable | 其他应付款(元) | |
| TotalLiability | 负债合计(元) | |
| PaidInCapital | 实收资本(或股本)(元) | |
| SurplusReserveFund | 盈余公积(元) | |
| MinorityInterests | 少数股东权益(元) | |
| TotalShareholderEquity | 所有者权益合计(元) | |
| TotalLiabilityAndEquity | 负债和所有者权益总计(元) | |
| TotalCurrentLiability | 流动负债合计(元) | |
| FinancialExpense | 财务费用(元) | 非金融类指标 |
| InvestIncome | 投资净收益(元) | |
| TotalNonCurrentLiability | 非流动负债合计(元) | |
| NonCurrentLiabilityIn1Year | 一年内到期的非流动负债(元) | |
| NonRecurringProfitLoss | 非经常性损益(元) | |
| InfoSourceCode | 信息来源编码 | 与 CT_SystemConst.DM 关联（LB=2181）；如 110101-年度报告、110102-半年度报告、110103-第一季报等 |
| BillReceivable | 应收票据 | |
| BillAccReceivable | 应收票据及应收账款 | |
| OtherReceivableED | 其他应收款(含利息和股利) | |
| OtherPayableED | 其他应付款(含利息和股利) | |
| CommonSE | 归属于普通股股东权益 | |

## 三、主要财务指标表（lc_mainindexnew）字段

> 来源表：`lc_mainindexnew`。在宽表 `daily_with_maindata_v2` 中字段统一加前缀 **`idx_`**，避免与 `lc_maindatanew` 重名。  
> 匹配规则：截至交易日最近一期（`idx_EndDate` ≤ 当日）。  
> 说明：源表 `CompanyCode` 已通过 `secumain` 挂入宽表，本表不再重复输出；`ID`/`UpdateTime`/`JSID`/`InsertTime` 未写入宽表。

| 字段名 | 中文解释 | 备注 |
|--------|----------|------|
| idx_EndDate | 截止日期 | 非空。报告期截止日；as-of 匹配关键字段 |
| idx_InfoPublDate | 信息发布日期 | 可空。多表衍生计算时取最大信息发布日期 |
| idx_EPS | 每股收益_期末股本摊薄(元/股) | 归属于母公司的净利润/该报告期末总股本 |
| idx_BasicEPS | 基本每股收益(元/股) | 新准则取实际披露数；旧准则取每股收益（加权） |
| idx_DilutedEPS | 稀释每股收益(元/股) | 新准则取实际披露数；旧准则按稀释性潜在普通股规则计算 |
| idx_NetAssetPS | 每股净资产(元/股) | 优先取定期报告披露；未披露则=(归母所有者权益-其他权益工具)/期末总股本 |
| idx_MainIncomePS | 每股营业收入(元/股) | 营业收入/该报告期期末总股本 |
| idx_OperProfitPS | 每股营业利润(元/股) | 营业利润/期末总股本 |
| idx_EBITPS | 每股息税前利润(元/股) | 息税前利润/期末总股本；金融类企业不计算 |
| idx_CapitalSurplusFundPS | 每股资本公积金(元/股) | 资本公积/期末总股本 |
| idx_OperCashFlowPS | 每股经营活动产生的现金流量净额(元/股) | 经营活动产生的现金流量净额/期末总股本 |
| idx_CashFlowPS | 每股现金流量净额(元/股) | 现金及现金等价物净增加额/期末总股本 |
| idx_NetProfit | 归属母公司净利润(元) | 取利润表披露值 |
| idx_NetProfitCut | 扣除非经常性损益后的归母净利润(元) | 取公布值 |
| idx_EBIT | 息税前利润(元) | 利润总额＋利息费用；利息费用优先取财务费用明细，否则用附注或财务费用代替；金融类不计算 |
| idx_EBITDA | 息税折旧摊销前利润(元) | EBIT+固定资产折旧+投资性房地产折旧+无形资产摊销+长期待摊费用摊销+使用权资产摊销/折旧；金融类不计算 |
| idx_OperatingProfitRatio | 营业利润率(%) | 营业利润/营业收入*100% |
| idx_GrossIncomeRatio | 销售毛利率(%) | (营业收入-营业成本)/营业收入*100%；金融类不计算 |
| idx_NetProfitRatio | 销售净利率(%) | 含少数股东损益的净利润/营业收入*100% |
| idx_TotalProfitCostRatio | 成本费用利润率(%) | 利润总额/成本费用总额*100%；成本费用=营业成本(金融用营业支出)+期间费用；金融类不计算 |
| idx_ROA | 总资产净利率(%) | 含少数股东损益的净利润*2/(期初总资产+期末总资产)*100% |
| idx_ROECut | 净资产收益率_扣除,摊薄(%) | 优先取披露值；未披露则=扣非归母净利润/期末归母股东权益*100% |
| idx_ROECutWeighted | 净资产收益率_扣除,加权(%) | 直接取公司定期报告披露数据 |
| idx_ROIC | 投入资本回报率(%) | EBIT*(1-有效税率)*2/(期初+期末全部投入资本)*100%；金融类不计算 |
| idx_CurrentRatio | 流动比率 | 流动资产合计/流动负债合计；金融类不计算 |
| idx_QuickRatio | 速动比率 | (流动资产合计-存货)/流动负债合计；金融类不计算 |
| idx_SuperQuickRatio | 超速动比率 | (货币资金+交易性金融资产+应收票据及应收账款+其他应收款)/流动负债合计；金融类不计算 |
| idx_OperCashInToCurrentDebt | 现金流动负债比 | 经营现金净流入/流动负债；金融类不计算 |
| idx_InterestCover | 利息保障倍数(倍) | 息税前利润/利息费用；利息费用≤0 不计算；金融类不计算 |
| idx_DebtAssetsRatio | 资产负债率(%) | 负债合计/资产合计*100% |
| idx_DebtEquityRatio | 产权比率(%) | 负债合计/所有者权益合计*100% |
| idx_DebtTangibleEquityRatio | 有形净值债务率(%) | 负债合计/有形净值*100%；有形净值=归母股东权益-(无形资产+开发支出+商誉+长期待摊费用+递延所得税资产) |
| idx_LongDebtToWorkingCapital | 非流动负债/营运资金(%) | 非流动负债合计/(流动资产-流动负债)；金融类不计算 |
| idx_OperatingRevenueGrowRate | 营业收入同比增长(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_OperProfitGrowRate | 营业利润同比增长(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_TotalProfeiGrowRate | 利润总额同比增长(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算。源字段名拼写为 TotalProfeiGrowRate |
| idx_NetProfitGrowRate | 净利润同比增长(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_NetAssetGrowRate | 净资产同比增长(%) | (本期-上年同期归母股东权益)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_TotalAssetGrowRate | 总资产同比增长(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_OperCashPSGrowRate | 每股经营活动产生的现金流量净额同比增长(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_SustainableGrowRate | 可持续增长率(%) | (本期净利润/期初归母股东权益)*本期留存收益率*100%；仅年度；见 RetainedEarningRatio |
| idx_ARTRate | 应收账款周转率(次) | 营业收入*2/(期初+期末应收账款)；金融类不计算 |
| idx_ARTDays | 应收账款周转天数(天/次) | N/应收账款周转率；一季90/中报180/三季270/年报360；金融类不计算 |
| idx_InventoryTRate | 存货周转率(次) | 营业成本*2/(期初+期末存货)；金融类不计算 |
| idx_InventoryTDays | 存货周转天数(天/次) | N/存货周转率；N 同季报规则；金融类不计算 |
| idx_FixedAssetTRate | 固定资产周转率(次) | 营业总收入*2/(期初+期末固定资产合计)；金融类不计算 |
| idx_EquityTRate | 股东权益周转率(次) | 营业总收入*2/(期初+期末净资产) |
| idx_TotalAssetTRate | 总资产周转率(次) | 营业总收入*2/(期初+期末资产合计) |
| idx_OperCycle | 营业周期(天/次) | 存货周转天数+应收账款周转天数；金融类不计算 |
| idx_CashEquivalentIncrease | 现金及现金等价物净增加额(元) | 现金流量表披露值 |
| idx_NetOperateCashFlow | 经营活动产生的现金流量净额(元) | 现金流量表披露值 |
| idx_GoodsSaleServiceRenderCash | 销售商品提供劳务收到的现金(元) | 金融类企业不计算 |
| idx_FreeCashFlow | 自由现金流量(元) | 息前税后利润+折旧与摊销-营运资金增加-资本支出；金融类不计算 |
| idx_NetProfitCashCover | 净利润现金含量(%) | 经营活动产生的现金流量净额/净利润*100% |
| idx_OperatingRevenueCashCover | 营业收入现金含量(%) | 销售商品、提供劳务收到的现金/营业收入*100%；金融类不计算 |
| idx_CashRateOfSales | 经营活动产生的现金流量净额/营业收入(%) | 经营现金流净额/营业收入*100% |
| idx_OperCashInToAsset | 总资产现金回收率(%) | 经营现金流净额*2/(期初+期末总资产)*100% |
| idx_CashEquivalentPS | 每股现金及现金等价物余额(元/股) | 现金及现金等价物期末余额/期末总股本 |
| idx_UndividedProfit | 每股未分配利润(元/股) | 未分配利润/期末总股本 |
| idx_AccumulationFundPS | 每股公积金(元/股) | (资本公积金+盈余公积金)/期末总股本 |
| idx_DividendPS | 每股股利(元/股) | 根据公司公布的分红方案确定 |
| idx_DividendCover | 股利保障倍数(倍) | 归母净利润/累计合计派现金额；派现为0或空则不计算 |
| idx_DividendPaidRatio | 股利支付率(%) | 累计合计派现金额/归母净利润*100% |
| idx_RetainedEarningRatio | 留存盈余比率(%) | 100%-股利支付率 |
| idx_CashDividendCover | 现金股利保障倍数(倍) | 经营现金流净额/累计合计派现金额；派现为0或空则不计算 |
| idx_WorkingCapital | 营运资金(元) | 流动资产合计-流动负债合计；金融类不计算 |
| idx_LongDebtToAsset | 长期借款/总资产 | 长期借款/总资产 |
| idx_BondsPayableToAsset | 应付债券/总资产 | 应付债券/总资产 |
| idx_EquityToAsset | 股东权益比率(%) | 股东权益合计/资产合计*100% |
| idx_LongDebtToEquity | 长期负债/股东权益合计 | 非流动负债合计/所有者权益合计；金融类不计算 |
| idx_LongAssetFitRate | 长期资产适合率 | (所有者权益+长期负债)/(固定资产净值+长期股权投资+可供出售金融资产+持有至到期投资)；金融类不计算 |
| idx_FixAssetRatio | 固定资产比率(%) | 固定资产/资产总额*100% |
| idx_IntangibleAssetRatio | 无形资产比率(%) | 无形资产/资产总额*100% |
| idx_EquityMultipler | 权益乘数 | 资产合计/股东权益合计 |
| idx_EPSTTM | 每股收益_TTM(元/股) | 归母净利润(TTM)/期末总股本 |
| idx_TotalOperatingRevenuePS | 每股营业总收入(元/股) | 营业总收入/该报告期期末总股本 |
| idx_OperatingRevenuePSTTM | 每股营业收入_TTM(元/股) | 营业收入(TTM)/期末总股本 |
| idx_SurplusReserveFundPS | 每股盈余公积(元/股) | 盈余公积/期末总股本 |
| idx_RetainedEarningsPS | 每股留存收益(元/股) | (盈余公积+未分配利润)/期末总股本 |
| idx_OperCashFlowPSTTM | 每股经营活动产生的现金流量净额_TTM(元/股) | 经营现金流净额(TTM)/期末总股本 |
| idx_CashFlowPSTTM | 每股现金流量净额_TTM(元/股) | 现金及现金等价物净增加额(TTM)/期末总股本 |
| idx_EnterpriseFCFPS | 每股企业自由现金流量(元/股) | 企业自由现金流量/期末总股本；金融类不计算 |
| idx_ShareHolderFCFPS | 每股股东自由现金流量(元/股) | [企业自由现金流-偿还债务现金+借款现金+发债现金]/期末总股本；金融类不计算 |
| idx_ROEAvg | 净资产收益率_平均,计算值(%) | 归母净利润*2/(期初+期末归母股东权益)*100% |
| idx_ROEWeighted | 净资产收益率_加权,公布值(%) | 公司定期报告披露数据 |
| idx_ROE | 净资产收益率_摊薄,公布值(%) | 优先取披露值；未披露则=归母净利润/期末归母股东权益*100% |
| idx_ROETTM | 净资产收益率_TTM(%) | 归母净利润(TTM)/期末归母股东权益*100% |
| idx_ROA_EBIT | 总资产报酬率(%) | 息税前利润*2/(期初+期末总资产)*100%；金融类不计算 |
| idx_ROA_EBITTTM | 总资产报酬率_TTM(%) | 息税前利润(TTM)/总资产(MRQ)*100%；金融类不计算 |
| idx_ROATTM | 总资产净利率_TTM(%) | 含少数股东损益的净利润(TTM)/总资产(MRQ)*100% |
| idx_NetProfitRatioTTM | 销售净利率_TTM(%) | 含少数股东损益的净利润(TTM)/营业收入(TTM)*100% |
| idx_GrossIncomeRatioTTM | 销售毛利率_TTM(%) | [营业收入(TTM)-营业成本(TTM)]/营业收入(TTM)*100%；金融类不计算 |
| idx_SalesCostRatio | 销售成本率(%) | 营业成本/营业收入*100%；金融类不计算 |
| idx_PeriodCostsRate | 销售期间费用率(%) | (销售费用+管理费用+财务费用+研发费用)/营业收入*100%；金融类不计算 |
| idx_PeriodCostsRateTTM | 销售期间费用率_TTM(%) | 期间费用(TTM)合计/营业收入(TTM)*100% |
| idx_NPToTOR | 净利润/营业总收入(%) | 非金融=净利润/营业总收入*100；金融=净利润/营业收入*100 |
| idx_NPToTORTTM | 净利润/营业总收入_TTM(%) | 非金融用营业总收入(TTM)；金融用营业收入(TTM) |
| idx_OperatingProfitToTOR | 营业利润/营业总收入(%) | 非金融用营业总收入；金融用营业收入 |
| idx_OperatingProfitToTORTTM | 营业利润/营业总收入_TTM(%) | 同上，TTM 口径 |
| idx_EBITToTOR | 息税前利润/营业总收入_杜邦分析(%) | 金融类企业不计算 |
| idx_EBITToTORTTM | 息税前利润/营业总收入_TTM(%) | EBIT(TTM)/营业总收入(TTM)*100%；金融类不计算 |
| idx_TOperatingCostToTOR | 营业总成本/营业总收入(%) | 金融类企业不计算 |
| idx_TOperatingCostToTORTTM | 营业总成本/营业总收入_TTM(%) | 营业总成本(TTM)/营业总收入(TTM)*100%；金融类不计算 |
| idx_OperatingExpenseRate | 销售费用/营业总收入(%) | 金融类企业不计算 |
| idx_OperatingExpenseRateTTM | 销售费用/营业总收入_TTM(%) | 销售费用(TTM)/营业总收入(TTM)*100%；金融类不计算 |
| idx_AdminiExpenseRate | 管理费用/营业总收入(%) | 金融类企业不计算 |
| idx_AdminiExpenseRateTTM | 管理费用/营业总收入_TTM(%) | 管理费用(TTM)/营业总收入(TTM)*100%；金融类不计算 |
| idx_FinancialExpenseRate | 财务费用/营业总收入(%) | 金融类企业不计算 |
| idx_FinancialExpenseRateTTM | 财务费用/营业总收入_TTM(%) | 财务费用(TTM)/营业总收入(TTM)*100%；金融类不计算 |
| idx_AssetImpaLossToTOR | 资产减值损失/营业总收入(%) | 非金融用营业总收入；金融用营业收入 |
| idx_AssetImpaLossToTORTTM | 资产减值损失/营业总收入_TTM(%) | 同上，TTM 口径 |
| idx_SEWithoutMIToTL | 归属母公司股东的权益/负债合计(%) | 归母股东权益/负债合计*100% |
| idx_SEWMIToInterestBearDebt | 归属母公司股东的权益/带息债务(%) | 归母股东权益/带息债务*100%；金融类不计算 |
| idx_TangibleAToInteBearDebt | 有形净值/带息债务(%) | 有形净值/带息债务*100%；金融类不计算 |
| idx_TangibleAToNetDebt | 有形净值/净债务(%) | 有形净值/净债务*100%；净债务=带息债务-货币资金；金融类不计算 |
| idx_EBITDAToTLiability | 息税折旧摊销前利润/负债合计 | 见 EBITDA；金融类不计算 |
| idx_NOCFToTLiability | 经营活动产生现金流量净额/负债合计 | 金融类企业不计算 |
| idx_NOCFToInterestBearDebt | 经营活动产生现金流量净额/带息债务 | 带息债务算法同有形净值/带息债务；金融类不计算 |
| idx_NOCFToCurrentLiability | 经营活动产生现金流量净额/流动负债 | 金融类企业不计算 |
| idx_NOCFToNetDebt | 经营活动产生现金流量净额/净债务 | 净债务算法同有形净值/净债务；金融类不计算 |
| idx_BasicEPSYOY | 基本每股收益同比增长(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_DilutedEPSYOY | 稀释每股收益同比增长(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_NPParentCompanyYOY | 归属母公司股东的净利润同比增长(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_NPParentCompanyCutYOY | 归属母公司股东的净利润(扣除)同比增长(%) | 扣非归母净利润同比；上期为0或空则不计算 |
| idx_NetOperateCashFlowYOY | 经营活动产生的现金流量净额同比增长(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_NAORYOY | 净资产收益率(摊薄)同比增长(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_EPSGrowRateYTD | 每股净资产相对年初增长率(%) | (本期-上年度末每股净资产)/ABS(上年度末)*100%；上年度末为0或空则不计算 |
| idx_SEWithoutMIGrowRateYTD | 归属母公司股东的权益相对年初增长率(%) | (本期-上年度末)/ABS(上年度末)*100%；上年度末为0或空则不计算 |
| idx_TAGrowRateYTD | 资产总计相对年初增长率(%) | (本期末-上年度末总资产)/ABS(上年度末)*100%；上年度末为0或空则不计算 |
| idx_AccountsPayablesTRate | 应付账款周转率(次) | 营业成本*2/(期初+期末应付账款)；金融类不计算 |
| idx_AccountsPayablesTDays | 应付账款周转天数(天/次) | N/应付账款周转率；N 同季报规则；金融类不计算 |
| idx_CurrentAssetsTRate | 流动资产周转率(次) | 营业总收入*2/(期初+期末流动资产合计)；金融类不计算 |
| idx_SaleServiceCashToOR | 销售商品提供劳务收到的现金/营业收入(%) | 金融类企业不计算 |
| idx_SaleServiceCashToORTTM | 销售商品提供劳务收到的现金/营业收入_TTM(%) | 销售商品提供劳务收到的现金(TTM)/营业收入(TTM)*100%；金融类不计算 |
| idx_CashRateOfSalesTTM | 经营活动产生的现金流量净额/营业收入_TTM(%) | 经营现金流净额(TTM)/营业收入(TTM)*100% |
| idx_NOCFToOperatingNI | 经营活动产生的现金流量净额/经营活动净收益(%) | 非金融：营业总收入-营业总成本；金融：营业收入-营业支出-(投资净收益等) |
| idx_NOCFToOperatingNITTM | 经营活动产生的现金流量净额/经营活动净收益_TTM(%) | 同上，TTM 口径 |
| idx_CapitalExpenditureToDM | 资本支出/折旧和摊销 | 购建固定无形和长期资产支付的现金/各类折旧摊销合计 |
| idx_CurrentAssetsToTA | 流动资产/总资产(%) | 金融类企业不计算 |
| idx_NonCurrentAssetsToTA | 非流动资产/总资产(%) | 金融类企业不计算 |
| idx_SEWithoutMIToTotalCapital | 归属母公司股东的权益/全部投入资本(%) | 归母股东权益/全部投入资本*100%；金融类不计算 |
| idx_InteBearDebtToTotalCapital | 带息债务/全部投入资本(%) | 带息债务/(股东权益含少数+带息债务)*100%；金融类不计算 |
| idx_CurrentLiabilityToTL | 流动负债/负债合计(%) | 金融类企业不计算 |
| idx_NonCurrentLiabilityToTL | 非流动负债/负债合计(%) | 金融类企业不计算 |
| idx_OperatingNIToTP | 经营活动净收益/利润总额(%) | 经营活动净收益算法见 NOCFToOperatingNI |
| idx_OperatingMIToTPTTM | 经营活动净收益/利润总额_TTM(%) | 源字段名为 OperatingMIToTPTTM |
| idx_InvestRAssociatesToTP | 对联营合营公司投资收益/利润总额(%) | 对联营合营公司投资收益/利润总额*100% |
| idx_InvestRAssociatesToTPTTM | 对联营合营公司投资收益/利润总额_TTM(%) | 同上，TTM 口径 |
| idx_ValueChangeNIToTP | 价值变动净收益/利润总额(%) | 价值变动净收益=投资净收益+公允价值变动净收益+汇兑收益 |
| idx_ValueChangeNIToTPTTM | 价值变动净收益/利润总额_TTM(%) | 同上，TTM 口径 |
| idx_NetNonOperatingIncomeToTP | 营业外收支净额/利润总额(%) | (营业外收入-营业外支出)/利润总额*100% |
| idx_NetNonOIToTPTTM | 营业外收支净额/利润总额_TTM(%) | 营业外收支净额(TTM)/利润总额(TTM)*100% |
| idx_TaxesToTP | 所得税/利润总额(%) | 所得税/利润总额*100% |
| idx_NPCutToTP | 扣除非经常损益后的归母净利润/净利润(%) | 扣非归母净利润/净利润*100%；扣非优先取公布值 |
| idx_EquityMultipler_DuPont | 权益乘数_杜邦分析 | (期初+期末资产总额)/(期初+期末归母股东权益) |
| idx_NPPCToNP_DuPont | 归属母公司股东的净利润/净利润(%)_杜邦分析 | 归母净利润/净利润*100% |
| idx_NPToTOR_DuPont | 净利润/营业总收入_杜邦分析(%) | 净利润/营业总收入*100%；金融类不计算 |
| idx_NPToTP_DuPont | 净利润/利润总额_杜邦分析(%) | 净利润/利润总额*100% |
| idx_TPToEBIT_DuPont | 利润总额/息税前利润_杜邦分析(%) | 利润总额/EBIT*100%；金融类不计算 |
| idx_EBITToTOR_DuPont | 息税前利润/营业总收入_杜邦分析(%) | 金融类企业不计算 |
| idx_AvgNPYOYPastFiveYear | 过去五年同期归属母公司净利润平均增幅(%) | 过去五年同期归母净利润同比的算术平均值 |
| idx_ORComGrowRate3Y | 营业收入3年复合增长率(%) | 三年前同期为正/负时分别用不同复合公式 |
| idx_NPPCCGrowRate3Y | 归属母公司股东的净利润3年复合增长率(%) | 三年前同期为正/负时分别用不同复合公式 |
| idx_EVWtoEBITDA | EVW/EBITDA(含货币资金) | 企业价值(含货币资金)/EBITDA；金融类不计算 |
| idx_EVNtoEBITDA | EVN/EBITDA(剔除货币资金) | 企业价值(剔除货币资金)/EBITDA；金融类不计算 |
| idx_InteBearDebtToTL | 带息债务率(%) | 带息债务/负债合计*100%；金融类不计算 |
| idx_BasicEPSGrowRate3Y | 基本每股收益3年复合增长率(%) | 三年前同期为正/负时分别用不同复合公式 |
| idx_DilutedEPSGrowRate3Y | 稀释每股收益3年复合增长率(%) | 三年前同期为正/负时分别用不同复合公式 |
| idx_TORGrowRate | 营业总收入同比增长率(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_TORGrowRate3Y | 营业总收入3年复合增长率(%) | 三年前同期为正/负时分别用不同复合公式 |
| idx_OperProfitGrowRate3Y | 营业利润3年复合增长率(%) | 三年前同期为正/负时分别用不同复合公式 |
| idx_TPGrowRate3Y | 利润总额3年复合增长率(%) | 三年前同期为正/负时分别用不同复合公式 |
| idx_NetProfitGrowRate3Y | 净利润3年复合增长率(%) | 三年前同期为正/负时分别用不同复合公式 |
| idx_NPParentCompanyCut3Y | 归属母公司股东的净利润(扣除)3年复合增长率(%) | 扣非归母净利润3年复合；正/负基期公式不同 |
| idx_NetOperateCashFlow3Y | 经营活动产生的现金流量净额3年复合增长率(%) | 三年前同期为正/负时分别用不同复合公式 |
| idx_OperCashPSGrowRate3Y | 每股经营活动产生的现金流量净额3年复合增长率(%) | 三年前同期为正/负时分别用不同复合公式 |
| idx_NAORGrowRate3Y | 净资产收益率(摊薄)3年复合增长率(%) | 三年前同期为正/负时分别用不同复合公式 |
| idx_NetAssetGrowRate3Y | 净资产3年复合增长率(%) | 归母股东权益3年复合；正/负基期公式不同 |
| idx_TotalAssetGrowRate3Y | 总资产3年复合增长率(%) | 三年前同期为正/负时分别用不同复合公式 |
| idx_FreeCashFlowToNPPC | 自由现金流与归属母公司净利润比率 | 企业自由现金流量/归母净利润；金融类不计算 |
| idx_CashWorkingIndex | 现金营运指数 | 经营现金流净额/(净利润+减值+折旧摊销等调整项)；金融类不计算 |
| idx_ROACut | 总资产净利率_不含少数股东损益(%) | 归母净利润*2/(期初+期末总资产)*100% |
| idx_ROACutTTM | 总资产净利率_不含少数股东损益_TTM(%) | 归母净利润(TTM)/总资产*100% |
| idx_EBITDAPS | 每股息税折旧前利润(元/股) | EBITDA/期末总股本；金融类不计算 |
| idx_AnnualizedROE | 年化净资产收益率(%) | ROE*N；一季N=4，中报N=2，三季N=4/3，年报N=1 |
| idx_AnnualizedROAEBIT | 年化总资产报酬率(%) | 总资产报酬率*N；N 同季报规则；金融类不计算 |
| idx_AnnualizedROA | 年化总资产净利率(%) | 总资产净利率*N；N 同季报规则 |
| idx_ROICTTM | 投入资本回报率_TTM(%) | EBIT*(1-有效税率)TTM/全部投入资本*100%；金融类不计算 |
| idx_AssetILossToOProfit | 资产减值损失/营业利润(%) | 资产减值损失/营业利润*100% |
| idx_NetProfToOpRevenTTM | 归属母公司股东的净利润/营业收入_TTM(%) | 归母净利润(TTM)/营业收入(TTM)*100% |
| idx_EBITToToAssetsTTM | 息税前利润/总资产_TTM(%) | EBIT(TTM)/资产总额*100%；金融类不计算 |
| idx_EBITDAToTOR | 息税折旧前利润/营业总收入(%) | EBITDA/营业总收入*100%；金融类不计算 |
| idx_OperatingProRatioTTM | 营业利润率_TTM(%) | 营业利润(TTM)/营业收入(TTM)*100% |
| idx_MainProfitProportion | 主营业务比率(%) | 营业利润/利润总额*100% |
| idx_TangibleAToTL | 有形资产/负债合计(%) | 有形资产净值/负债合计*100%；金融类不计算 |
| idx_NOCFToTotalNonCurLia | 经营活动产生现金流量净额/非流动负债(%) | 经营现金流净额/非流动负债*100%；金融类不计算 |
| idx_NOCFInterestCover | 现金流量利息保障倍数(倍) | 经营现金流净额/利息费用；利息费用≤0 不计算；金融类不计算 |
| idx_CashRatio | 现金比率(%) | (货币资金+交易性金融资产+应收票据)/流动负债合计*100%；金融类不计算 |
| idx_OperCashInToDueDebt | 现金到期债务比 | 经营现金流净额/(短期借款+一年内到期非流动负债+应付票据)；金融类不计算 |
| idx_NetAssetLiabilityRatio | 净资产负债率(%) | 负债合计/归母股东权益*100% |
| idx_NetLiabilityRatio | 净负债率(%) | (带息债务-货币资金)/所有者权益*100%；金融类不计算 |
| idx_NetNoFCFToCLiability | 非筹资性现金净流量与流动负债的比率(%) | (经营+投资现金流净额)/流动负债合计*100%；金融类不计算 |
| idx_NetNoFCFToTLiability | 非筹资性现金净流量与负债总额的比率(%) | (经营+投资现金流净额)/负债合计*100% |
| idx_LongDebtRatio | 长期负债占比 | (长期借款+应付债券+长期应付款+专项应付款)/负债合计 |
| idx_EBITDAToIntBearDebt | 息税折旧前利润/带息债务(%) | EBITDA/带息债务*100%；金融类不计算 |
| idx_EBITDAToInttFinExp | 息税折旧前利润/利息费用(%) | EBITDA/利息费用*100%；利息费用≤0 不计算；金融类不计算 |
| idx_EntireliabToEBITDA | 全部债务/息税折旧前利润 | 全部债务/EBITDA；全部债务含长短期借款、应付债券、应付票据等；金融类不计算 |
| idx_CashToCurliability | 货币资金/短期债务(%) | 货币资金/短期债务*100%；短期债务=短借+应付票据+交易性金融负债+一年内到期非流动负债 |
| idx_ToOpCostGrowRate | 营业总成本同比增长(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_ToLiabGrowRate | 总负债同比增长(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_CashEqIncreaseYOY | 现金净流量同比增长(%) | (本期-上年同期现金及现金等价物净增加额)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_CashEquivalGrowRate | 货币资金增长率(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_FAExpansionRate | 固定资产投资扩张率(%) | (本期-上年同期固定资产)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_NetOperCycle | 净营业周期(天/次) | 存货周转天数+应收账款周转天数-应付账款周转天数；金融类不计算 |
| idx_WorkingCapitalTurDays | 营运资金周转天数(天/次) | 存货+应收-应付+预付-预收周转天数；金融类不计算 |
| idx_TotalAssetTRateTTM | 总资产周转率_TTM(次) | 营业总收入(TTM)*2/(上年同期+期末资产合计) |
| idx_WorkingCaitalTRate | 营运资本周转率(次) | 营业总收入*2/(期初+期末营运资本)；源字段拼写为 WorkingCaitalTRate；金融类不计算 |
| idx_NonCurrentATRate | 非流动资产周转率(次) | 营业总收入*2/(期初+期末非流动资产合计)；金融类不计算 |
| idx_NetOperCFToOperProfTTM | 经营活动产生的现金流量净额/营业利润_TTM(%) | 经营现金流净额(TTM)/营业利润(TTM)*100% |
| idx_NetOperCFRatio | 经营活动产生的现金流量净额占比 | 经营/(经营+投资+筹资)现金流净额 |
| idx_NetInvestCFRatio | 投资活动产生的现金流量净额占比 | 投资/(经营+投资+筹资)现金流净额 |
| idx_NetFinaCFRatio | 筹资活动产生的现金流量净额占比 | 筹资/(经营+投资+筹资)现金流净额 |
| idx_NetOperCFToToOperReve | 经营现金净流量/营业总收入(%) | 经营现金流净额/营业总收入*100% |
| idx_NetOperCFToToAssets | 全部资产现金回收率(%) | 经营现金流净额/总资产*100% |
| idx_ActualDividendPS | 每股股利(元/股)(税后) | 公布值，根据分红方案确定 |
| idx_DebtARatioCutADRecp | 剔除预收账款后的资产负债率(%) | (负债合计-预收款项-合同负债)/(资产总额-预收账款-合同负债)*100 |
| idx_DebtARatioCutADReNo | 剔除预收账款后的资产负债率_公告口径(%) | (负债合计-预收款项-合同负债)/资产总额*100 |
| idx_NetTangibleAToTA | 有形资产/总资产(%) | 有形资产净值/总资产*100%；金融类不计算 |
| idx_TotalCLiaToSEWMI | 流动负债权益比率(%) | 流动负债合计/归母股东权益合计*100%；金融类不计算 |
| idx_TotalNonCLiaToSEWMI | 非流动负债权益比率(%) | 非流动负债合计/归母股东权益合计*100%；金融类不计算 |
| idx_TotalNonCurLiaToSEWMI | 长期资本负债率(%) | 非流动负债合计/(非流动负债合计+归母股东权益)*100%；金融类不计算 |
| idx_TotalNonCurAToSEWMI | 资本固定化比率(%) | 非流动资产合计/归母股东权益*100%；金融类不计算 |
| idx_ToProfToOperProfitTTM | 营业利润/利润总额_TTM(%) | 营业利润(TTM)/利润总额(TTM)*100% |
| idx_ToProfToOperRevenueTTM | 利润总额/营业收入_TTM(%) | 利润总额(TTM)/营业收入(TTM)*100% |
| idx_DebtEquityRatio_DuPont | 产权比率_杜邦分析(%) | (期初+期末负债合计)/(期初+期末归母股东权益)*100% |
| idx_EPSCut | 基本每股收益(扣除)(元/股) | 优先原文披露；未披露则=扣除后净利润/期末股本 |
| idx_NetAssetPSAdjusted | 调整后每股净资产(元/股) | 取原文披露值 |
| idx_EBITAssetRatio | 息税前利润/资产总额(%) | EBIT/资产总额*100%；金融企业不计算 |
| idx_EBIAT | 息前税后利润(元) | EBIT*(1-有效税率)；金融企业不计算 |
| idx_TaxRatio | 销售税金率(%) | 非金融=税金及附加/营业总收入*100；金融=税金及附加/营业收入*100 |
| idx_EVW | EVW(含货币资金) | 总市值+带息债务；金融企业不计算 |
| idx_EVN | EVN(剔除货币资金) | 总市值-货币资金+带息债务；金融企业不计算 |
| idx_NonRecurrGLProportion | 非经常性损益比率(%) | 非经常性损益/净利润*100 |
| idx_CapitalReturn | 资本收益率(%) | EBIT/((期初+期末长期负债+期初+期末股东权益)/2)*100；金融企业不计算 |
| idx_EquityGrowRate | 资本保值增值率(%) | 期末所有者权益/期初所有者权益*100 |
| idx_RetainedEarningAsset | 留存收益/资产总额(%) | (盈余公积+未分配利润)/资产总额*100 |
| idx_RepaymentCover | 偿债倍数(倍) | EBIT/[利息+本金偿还/(1-税率)]；税率取有效税率；金融企业不计算 |
| idx_WorkingCapitalAsset | 营运资金/资产总额 | 金融企业不计算 |
| idx_EPSYOY | 每股收益同比增长(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_EPSGrowRate3Y | 每股收益3年复合增长率(%) | 三年前同期为正/负时分别用不同复合公式 |
| idx_PBVGrowRate | 每股净资产同比增长(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_PBVGrowRate3Y | 每股净资产3年复合增长率(%) | 三年前同期为正/负时分别用不同复合公式 |
| idx_CapitalStockGrowth | 股本同比增长数(元) | 本期实收资本(或股本)-上年同期实收资本(或股本) |
| idx_ARTRGrowRate | 应收账款周转率增长率(%) | (本期-上年同期)/ABS(上年同期)*100%；金融类不计算 |
| idx_FATRGrowRate | 固定资产周转率增长率(%) | (本期-上年同期)/ABS(上年同期)*100%；金融类不计算 |
| idx_InventoryTRGrowRate | 存货周转率增长率(%) | (本期-上年同期)/ABS(上年同期)*100%；金融类不计算 |
| idx_CashEqGroRate | 现金及现金等价物增长率(%) | (本期-上年同期期末余额)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_CashPayStaffRatio | 支付给职工的现金比率(%) | 用于职工的各项现金支出/销售商品出售劳务收回的现金；金融企业不计算 |
| idx_FinancingCashGrowRate | 筹资活动产生的现金流量净额增长率(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_InvestCashGrowRate | 投资活动产生的现金流量净额增长率(%) | (本期-上年同期)/ABS(上年同期)*100%；上期为0或空则不计算 |
| idx_NetOperateCashProfit | 经营活动现金净流量与净利润差(元) | 经营现金流净额-净利润 |
| idx_CashToMeetInvestNeeds | 现金满足投资比率(%) | 经营现金流净额/(购建长期资产现金-存货减少+分配股利利润或偿付利息现金)；金融企业不计算 |
| idx_ExternalFinanceRatio | 外部融资比率(%) | (经营性应付项目增减净额+筹资现金流入量)/现金流入量总额 |
| idx_OperCashStability | 营业现金稳定性 | 计提的折旧费用/经营活动产生的现金净流量 |
| idx_DividendTTM | 股息TTM(元) | 根据累计派现合计计算 |
| idx_Dividend | 累计派现合计(元) | 本年年初至本报告期，按分红实施方案累计分红合计 |
| idx_EquityFixedAssetRatio | 股东权益与固定资产比率(%) | 股东权益合计(含少数)/固定资产*100% |
| idx_FinancialLeverage | 财务杠杆效率 | 净资产收益率/资产报酬率；金融企业不计算 |
