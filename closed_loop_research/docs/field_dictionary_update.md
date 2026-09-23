# 字段说明补录记录

2026-09-21：修复原始字段目录生成器未关联中文字段说明的问题。

- 来源：用户提供的 `F:/my_code_file/因子构建/数据/日K表字段说明.md`，按原始字段名精确匹配，不混淆财务原值字段和带 `idx_` 前缀的指标字段。
- 原文副本保存在 `app/resources/日K表字段说明.md`；SHA256为 `8807de5f55d6f12a4b8b34f0ddfdb27e9dc37d35c8dc346bf1776a25f634ea52`。
- 441个源字段中425个匹配，文档425条全部使用，无重复或多余条目。
- 文档未收录16个证券基础字段：InnerCode、CompanyCode、ChiName、ChiNameAbbr、EngName、EngNameAbbr、SecuAbbr、ChiSpelling、SecuMarket、SecuCategory、ListedDate、ListedSector、ListedState、ISIN、ExtendedAbbr、ExtendedSpelling。显示“提供的字段说明文档未收录此字段”，没有猜测填充。
- 数据中心“字段与质量”直接展示中文说明、文档备注、导入/训练状态和说明出处；支持按字段名、中文说明、备注搜索。出处保存文档名、SHA256、章节和行号。
- 新导入目录自动包含说明；已有数据通过独立展示层补充，未重写冻结manifest、行情、研究快照、模型或历史结果。说明文档不改变训练白名单、单位核验或过滤权限。
- 源文档是字段语义依据，不是历史时点已核验的证明。例如按EndDate关联财务与“最新披露”不保证当时可见；market_code文档中的枚举也不能覆盖原始数据的实际观测冲突。
- 27项相关Python回归通过；JavaScript语法检查和已有表单回归通过。测试包括精确匹配、带转义竖线备注、来源指纹/行号、重复条目拒绝、缓存隔离、旧快照不变与过滤禁用不被解除。
- 已在实际浏览器验证ROE说明与备注、中文“开盘价”搜索、ListedDate未收录标记。正式接口确认425项说明已生效、原manifest文件指纹不变，9个冻结模型仍满足当前数据就绪要求。

现有真实快照的匹配清单和保留身份记录见 `workspace/system_v1/field_dictionary_update.json`。

后续更新说明时，应更新独立资源副本并保留来源记录；不直接编辑旧快照的指纹。资源解析缓存按文档内容建立，更新说明后无需重导19.8GB行情。
