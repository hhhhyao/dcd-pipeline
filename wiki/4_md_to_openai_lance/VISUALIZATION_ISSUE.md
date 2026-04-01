# DCD 可视化问题说明

## 核心问题

如果平台侧声称支持 OpenAI 格式的可视化，按我们的理解，不应该只支持：

```json
{"messages": [{"role": "user", "content": "纯字符串"}]}
```

还应该支持 `messages[].content` 是 `list[dict]` 的场景，并按顺序展示图文交织内容，例如：

```json
{
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "段落 1"},
        {"type": "image_url", "image_url": {"url": "images/part/hash/file.jpg"}},
        {"type": "text", "text": "段落 2"}
      ]
    }
  ]
}
```

也就是：

- `text` item 渲染为文本
- 图片 item 渲染为图片
- 整体按顺序展示为图文交织内容

但当前 DCD 不是这样工作的。

## 当前实际情况

DCD 现在真正支持显示图片的方式，本质上还是“占位符字符串协议”：

- markdown: `![](images/<id>)`
- html: `<img src="images/<id>">`

也就是说，前端当前依赖的是：

1. 先把内容当作 markdown / html 字符串
2. 再识别其中的 `images/<id>` pattern
3. 把它重写成真实图片 URL

而不是直接渲染结构化的图文 block。

## 我们当前的数据

当前 `4_md_to_openai_lance` 产出的单条样本更接近结构化图文内容，而不是 conversation：

```json
[
  {"type": "text", "text": "段落 1\n\n"},
  {"type": "image", "image_file": {"image": "images/part/hash/file.jpg"}},
  {"type": "text", "text": "\n\n段落 2"}
]
```

并且：

- 没有 `role`
- 不是多轮对话
- 不希望为了前端兼容，重新退回到 markdown / placeholder 的方案

## 为什么不希望用占位符方案

不希望把图片重新编码回文本中的：

- `![](images/<id>)`
- `<image>`
- `<img_0>`
- 其他自定义 token

原因是：

- 这会把结构化图文数据退化成字符串协议
- 容易和正文中的真实文本 pattern 冲突
- 不能准确表达训练样本原本的图文结构

## 当前表现

现在这类数据在 DCD 中的表现是：

- 列表页缩略图仍可显示，因为 `info.image_ids` 还在
- text 详情页不能把 JSON 中的图片项渲染成真实图片
- 最终更接近显示原始 JSON，而不是图文交织样本

## 想确认的平台支持点

想请平台侧确认：

1. 是否已有现成 renderer，可以直接支持 OpenAI 风格的 `content: list[dict]`
2. 如果没有，是否可以新增对这类结构的可视化支持

期望支持的能力是：

- `messages[].content` 支持 `list[dict]`
- `text` item 按文本展示
- `image_url` / `image_file` item 按图片展示
- 整体按顺序渲染为图文交织内容

## 结论

当前 DCD 对“OpenAI 格式”的支持，更准确地说是：

- 支持字符串型 `content`
- 支持基于 markdown / html 占位符的图片显示
- 还不支持结构化 `list[dict]` content 的图文交织可视化
