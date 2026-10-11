> 历史设计资料：当前服务已改为阿里云四模型接入，取消离线 Mock 和界面密钥输入，并独立处理服务错误。当前启动和配置请以项目根目录 README.md 与《接入阿里云调试说明.md》为准。

# Step 6 · Micro Action

输入：intent、emotion、risk_level、action_declined、user_input。输出：一个 `MicroAction` 或 null。

仅当 intent=Action、risk_level=Normal、emotion≠Overwhelmed 且用户没有持续拒绝时触发。明确重新请求行动可解除此前拒绝。Vent / Companion / Reflect / Play、风险未明或较高、情绪被压倒、用户拒绝时都不生成。

JSON 示例：`{"title":"如果愿意，可以先写下最想处理的一件事；不做也没关系。","optional":true}`。不触发时为 `null`，不是空任务列表。

Mock 只提供一个通用小步骤。用户可以在 Demo 选择“完成了”“暂时不做”“不适合我”，反馈仅进入当前短期会话，后两者保持拒绝状态。不会奖励关系等级，也不会自动生成第二项任务。再次行动需要用户明确提出。

与安全支持区别：联系现实支持是安全分支的支持信息，不是 Micro Action，不计完成率，不给宠物成长奖励。安全 UI 不展示任务完成按钮。

实现位于 `momo/graph.py` 的独立 `micro_action_node`，最终回复节点负责合并并核查上限。输出结构在 `models.py`，测试覆盖拒绝、压倒状态、高风险和显式行动请求。
