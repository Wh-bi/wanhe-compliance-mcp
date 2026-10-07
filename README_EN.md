# Wanhe Compliance MCP Server

Chinese content compliance checking for AI agents — advertising-law prohibited terms
and AI-generated content labeling, exposed as MCP tools.

**Zero external dependencies.** Uses the official `mcp` library when available,
otherwise falls back to a built-in stdio JSON-RPC implementation with identical
behaviour. No `pip install` required to run.

---

## What it solves

Writing Chinese commercial content (e-commerce listings, short-video scripts,
WeChat articles, AI-generated images and text) commonly violates three rules:

1. **Advertising-law prohibited terms** — 「全网最」 (best in the entire network),
   「100%」, 「国家级」 (national-level), 「根治」 (cure), 「包过」 (guaranteed pass),
   「稳赚不赔」 (guaranteed profit, no loss)
2. **AI-generated content labeling** — China's *Measures for Labeling AI-Generated
   Synthetic Content* require both a visible label **and** metadata marking
3. **Missing organisational process** — security assessments, algorithm filing,
   separate consent for sensitive data

This server exposes these checks as MCP tools so your agent can run them while
you write, and cite the exact legal provision for each finding.

---

## Tools

| Tool | Purpose | Input |
|---|---|---|
| `check_content` | Check text for advertising-law risk. Returns per-issue: type / position / matched text / **legal basis** / suggested fix | `text` (≤2000 chars) |
| `check_ai_label` | Detect AI-generation wording and flag China AI-labeling requirements | `text` |

### Legal bases covered (free tier)

- **Advertising Law of the PRC** — Art. 9 (superlatives), Art. 17 & 18 (disease
  treatment / health-food claims), Art. 28 (false advertising)
- **Food Safety Law** — Art. 73 (food ads may not claim disease prevention/treatment)
- **AI-Generated Synthetic Content Labeling Measures** — Art. 4 & 5, plus mandatory
  national standard **GB 45438-2025**

---

## Install

### Claude Desktop

Edit `claude_desktop_config.json`
(Windows: `%APPDATA%\Claude\claude_desktop_config.json`;
macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "wanhe-compliance": {
      "command": "python",
      "args": ["/absolute/path/mcp_compliance_server.py"]
    }
  }
}
```

Restart Claude Desktop. `check_content` and `check_ai_label` will appear in the
tool list.

### Cursor / Cline / other MCP clients

Use the same `command` + `args` pair (stdio transport).

### Verify locally

```bash
python mcp_compliance_server.py --selftest
```

Prints server info and runs one example check.

---

## Example

Ask your agent:

> Check this short-video script for compliance:
> 本店橙子全网最甜，100%无添加，彻底根治失眠，国家级免检产品

The agent calls `check_content` and receives:

```json
{
  "ok": true,
  "tier": "free",
  "verdict": "存在高风险问题",
  "summary": "共 7 条（高风险 7 · 待确认 0 · 提示 0）",
  "issues": [
    {"type": "绝对化用语", "matched": "全网最", "position": "第 5 字符起",
     "basis": "《广告法》第9条第(三)项",
     "suggestion": "删去范围性绝对表述"},
    {"type": "承诺性用语", "matched": "100%", "position": "第 10 字符起",
     "basis": "《广告法》第9条、第28条（虚假广告）",
     "suggestion": "改为真实可验证的表述，或删去"}
  ]
}
```

---

## Design principles

### 1. Prefer missing a violation over raising a false alarm

A compliance tool that cries wolf loses trust immediately. Rules therefore
require **co-occurring context**:

- A disease name alone is **not** flagged (e.g. 「高血压患者请在医师指导下用药」 —
  a legitimate medical instruction)
- 「康复器材」 (rehabilitation equipment) and 「康复中心」 (rehabilitation centre)
  are **not** flagged — they are lawful product and business names
- Only 「claim verb + disease name」 together is flagged

### 2. No fabricated findings

When nothing is found, the tool says so explicitly. It never invents issues to
appear useful.

### 3. Reproducible

Same input, same output — rule engine, not model inference.

---

## Free tier vs cloud tier

| | Free (this server) | Cloud |
|---|---|---|
| Rules | 12 high-frequency rules, **offline, no per-call cost** | Full 21-rule set, continuously updated |
| Limits | 2,000 chars/check · 30 checks per session | No limits |
| AI-labeling verdict | Wording detection only | Full verdict (visible label + metadata) |
| Cross-regulation checks | — | ✓ |
| 17-item self-assessment | — | ✓ |
| Position de-duplication | — | ✓ |

Cloud endpoint: `POST https://wanhetools.top/api/a2m/demo/a2m/resource`
Returns `402 Payment Required` with a `Payment-Needed` header; retry with
`Payment-Proof` after payment. Details: https://wanhetools.top/compliance-check

---

## Disclaimer

This tool performs **rule matching and legal-provision citation only**.
It does **not** constitute legal advice. Consult a qualified lawyer for
compliance decisions.

## Privacy

- The free tier runs **entirely locally**; your content never leaves your machine
- No telemetry, no usage collection, no network requests

## License

MIT
