#!/usr/bin/env node
/**
 * latex-to-print.mjs — 把 LaTeX 源码转成"印刷体感"的纯 Unicode 文本。
 *
 *   node bin/latex-to-print.mjs --text '$\frac{x^{2}}{1+\sqrt{1-x^{2}}}$'
 *   node bin/latex-to-print.mjs <file.md> [-o <out.md>]
 *   echo '...' | node bin/latex-to-print.mjs -
 *
 * 为什么要有它：聊天渠道没有数学渲染器（见 SKILL.md §0.0），唯一的"印刷体"通路是把
 * LaTeX 翻成 Unicode 字符。手工翻容易漏（尤其 \frac/\sqrt/上下标），机器翻才一致。
 * 映射表参考社区现成做法，取同一套约定：
 *   - unicodeit（svenkreiss，pip/npm 可装，Obsidian 插件即基于它）
 *   - Pandoc `--to=plain`（"render TeX math as far as possible using unicode characters"）
 *   - 各在线 LaTeX→Unicode 转换器的公开映射说明（1500+ 符号表）
 * 本脚本自带映射表，不依赖网络与第三方包；输出仍是普通 UTF-8 文本，可复制、可检索。
 */
import fs from 'node:fs';

// ---------- 上下标 ----------
const SUP = { '0':'⁰','1':'¹','2':'²','3':'³','4':'⁴','5':'⁵','6':'⁶','7':'⁷','8':'⁸','9':'⁹',
  '+':'⁺','-':'⁻','−':'⁻','=':'⁼','(':'⁽',')':'⁾','n':'ⁿ','i':'ⁱ',
  a:'ᵃ',b:'ᵇ',c:'ᶜ',d:'ᵈ',e:'ᵉ',f:'ᶠ',g:'ᵍ',h:'ʰ',j:'ʲ',k:'ᵏ',l:'ˡ',m:'ᵐ',o:'ᵒ',p:'ᵖ',
  r:'ʳ',s:'ˢ',t:'ᵗ',u:'ᵘ',v:'ᵛ',w:'ʷ',x:'ˣ',y:'ʸ',z:'ᶻ','T':'ᵀ','+':'⁺',"'":'′','′':'′' };
const SUB = { '0':'₀','1':'₁','2':'₂','3':'₃','4':'₄','5':'₅','6':'₆','7':'₇','8':'₈','9':'₉',
  '+':'₊','-':'₋','−':'₋','=':'₌','(':'₍',')':'₎',
  a:'ₐ',e:'ₑ',h:'ₕ',i:'ᵢ',j:'ⱼ',k:'ₖ',l:'ₗ',m:'ₘ',n:'ₙ',o:'ₒ',p:'ₚ',r:'ᵣ',s:'ₛ',t:'ₜ',
  u:'ᵤ',v:'ᵥ',x:'ₓ' };

// ---------- 命令表 ----------
const CMD = {
  // 希腊
  alpha:'α',beta:'β',gamma:'γ',delta:'δ',epsilon:'ε',varepsilon:'ε',zeta:'ζ',eta:'η',
  theta:'θ',vartheta:'ϑ',iota:'ι',kappa:'κ',lambda:'λ',mu:'μ',nu:'ν',xi:'ξ',pi:'π',varpi:'ϖ',
  rho:'ρ',varrho:'ϱ',sigma:'σ',varsigma:'ς',tau:'τ',upsilon:'υ',phi:'φ',varphi:'φ',chi:'χ',
  psi:'ψ',omega:'ω',Gamma:'Γ',Delta:'Δ',Theta:'Θ',Lambda:'Λ',Xi:'Ξ',Pi:'Π',Sigma:'Σ',
  Upsilon:'Υ',Phi:'Φ',Psi:'Ψ',Omega:'Ω',
  // 运算与关系
  times:'×',div:'÷',pm:'±',mp:'∓',cdot:'·',ast:'∗',star:'⋆',circ:'∘',bullet:'∙',
  le:'≤',leq:'≤',leqslant:'≤',ge:'≥',geq:'≥',geqslant:'≥',ne:'≠',neq:'≠',equiv:'≡',
  approx:'≈',simeq:'≃',sim:'∼',propto:'∝',ll:'≪',gg:'≫',asymp:'≍',cong:'≅',
  in:'∈',notin:'∉',ni:'∋',subset:'⊂',subseteq:'⊆',supset:'⊃',supseteq:'⊇',
  cup:'∪',cap:'∩',setminus:'∖',emptyset:'∅',varnothing:'∅',forall:'∀',exists:'∃',
  nexists:'∄',neg:'¬',lnot:'¬',land:'∧',wedge:'∧',lor:'∨',vee:'∨',oplus:'⊕',otimes:'⊗',
  perp:'⊥',parallel:'∥',angle:'∠',triangle:'△',square:'□',therefore:'∴',because:'∵',
  // 大算符
  sum:'Σ',prod:'Π',coprod:'∐',int:'∫',iint:'∬',iiint:'∭',oint:'∮',nabla:'∇',partial:'∂',
  infty:'∞',aleph:'ℵ',hbar:'ℏ',ell:'ℓ',Re:'ℜ',Im:'ℑ',wp:'℘',
  // 箭头
  to:'→',rightarrow:'→',longrightarrow:'⟶',leftarrow:'←',leftrightarrow:'↔',
  Rightarrow:'⇒',Leftarrow:'⇐',Leftrightarrow:'⇔',implies:'⇒',iff:'⇔',mapsto:'↦',
  uparrow:'↑',downarrow:'↓',updownarrow:'↕',hookrightarrow:'↪',
  // 杂项
  ldots:'…',dots:'…',cdots:'⋯',vdots:'⋮',ddots:'⋱',prime:'′',degree:'°',
  checkmark:'✓',dag:'†',S:'§',P:'¶',copyright:'©',dotsb:'⋯',
  angle_:'∠',lceil:'⌈',rceil:'⌉',lfloor:'⌊',rfloor:'⌋',langle:'⟨',rangle:'⟩',
  lVert:'‖',rVert:'‖',Vert:'‖',vert:'|',mid:'|',
  space:' ',quad:'  ',qquad:'    ',thinspace:' ',',':' ',';':' ','!':'',
  // 黑板体 / 花体（单字母常用）
  'mathbb R':'ℝ','mathbb N':'ℕ','mathbb Z':'ℤ','mathbb Q':'ℚ','mathbb C':'ℂ','mathbb E':'𝔼',
  'mathbb P':'ℙ','mathcal L':'ℒ','mathcal O':'𝒪','mathcal H':'ℋ',
};
const BB = { R:'ℝ',N:'ℕ',Z:'ℤ',Q:'ℚ',C:'ℂ',E:'𝔼',P:'ℙ',H:'ℍ',F:'𝔽',D:'𝔻',K:'𝕂',B:'𝔹' };
const CAL = { L:'ℒ',O:'𝒪',H:'ℋ',E:'ℰ',F:'ℱ',M:'ℳ',B:'ℬ',P:'𝒫',R:'ℛ',S:'𝒮',T:'𝒯',D:'𝒟',
  A:'𝒜',N:'𝒩',C:'𝒞',G:'𝒢',I:'ℐ',J:'𝒥',K:'𝒦',U:'𝒰',V:'𝒱',W:'𝒲',X:'𝒳',Y:'𝒴',Z:'𝒵' };

// ---------- 小工具 ----------
const readBrace = (s, i) => {           // s[i] === '{' → 返回 [内容, 结束后的下标]
  let depth = 0, out = '';
  for (let j = i; j < s.length; j++) {
    const c = s[j];
    if (c === '{') { depth++; if (depth === 1) continue; }
    if (c === '}') { depth--; if (depth === 0) return [out, j + 1]; }
    out += c;
  }
  return [out, s.length];
};
// 单字符 → 上下标字形；多字符 → ^(...)/_(...)（与 SKILL.md §0.0 的规则一致，且更不依赖字体覆盖）
const toSuper = (t) => (t.length === 1 && t in SUP) ? SUP[t]
                     : (/^′+$/.test(t) ? t : '^(' + tidy(t) + ')');
const toSub   = (t) => (t.length === 1 && t in SUB) ? SUB[t] : '_(' + tidy(t) + ')';
const tidy = (t) => t.replace(/\s*([+−\-×·])\s*/g, '$1').replace(/-/g, '−');
const needParen = (t) => /[+\-−=,·×/]|\s/.test(t.trim()) && t.trim().length > 1;
const mapLetters = (t, table) => [...t].map((c) => table[c] ?? c).join('');

const BF = { A:'𝐀',B:'𝐁',C:'𝐂',D:'𝐃',E:'𝐄',F:'𝐅',G:'𝐆',H:'𝐇',I:'𝐈',J:'𝐉',K:'𝐊',L:'𝐋',M:'𝐌',
  N:'𝐍',O:'𝐎',P:'𝐏',Q:'𝐐',R:'𝐑',S:'𝐒',T:'𝐓',U:'𝐔',V:'𝐕',W:'𝐖',X:'𝐗',Y:'𝐘',Z:'𝐙',
  a:'𝐚',b:'𝐛',c:'𝐜',d:'𝐝',e:'𝐞',f:'𝐟',g:'𝐠',h:'𝐡',i:'𝐢',j:'𝐣',k:'𝐤',l:'𝐥',m:'𝐦',
  n:'𝐧',o:'𝐨',p:'𝐩',q:'𝐪',r:'𝐫',s:'𝐬',t:'𝐭',u:'𝐮',v:'𝐯',w:'𝐰',x:'𝐱',y:'𝐲',z:'𝐳' };
const IT = { A:'𝐴',B:'𝐵',C:'𝐶',D:'𝐷',E:'𝐸',F:'𝐹',G:'𝐺',H:'𝐻',I:'𝐼',J:'𝐽',K:'𝐾',L:'𝐿',M:'𝑀',
  N:'𝑁',O:'𝑂',P:'𝑃',Q:'𝑄',R:'𝑅',S:'𝑆',T:'𝑇',U:'𝑈',V:'𝑉',W:'𝑊',X:'𝑋',Y:'𝑌',Z:'𝑍',
  a:'𝑎',b:'𝑏',c:'𝑐',d:'𝑑',e:'𝑒',f:'𝑓',g:'𝑔',h:'ℎ',i:'𝑖',j:'𝑗',k:'𝑘',l:'𝑙',m:'𝑚',
  n:'𝑛',o:'𝑜',p:'𝑝',q:'𝑞',r:'𝑟',s:'𝑠',t:'𝑡',u:'𝑢',v:'𝑣',w:'𝑤',x:'𝑥',y:'𝑦',z:'𝑧' };

function convertMath(src) {
  let s = ' ' + src + ' ';
  const STRUCT = /\\(?:sqrt\s*(\[[^\]]*\])?\s*\{|[dt]?frac\s*\{|text\s*\{|mathrm\s*\{|operatorname\s*\{|mbox\s*\{|mathbf\s*\{|mathit\s*\{|mathsf\s*\{|mathbb\s*\{|mathcal\s*\{|bar\s*\{|hat\s*\{|tilde\s*\{|dot\s*\{|ddot\s*\{|vec\s*\{|overline\s*\{|underline\s*\{)/;
  let guard = 0;
  while (guard++ < 400) {
    const m = STRUCT.exec(s);
    if (!m) break;
    const cmd = /^\\[a-zA-Z]+/.exec(m[0])[0].slice(1);
    const braceAt = m.index + m[0].length - 1;          // 指向结构命令的 '{'
    const [A, afterA] = readBrace(s, braceAt);
    const at = m.index;
    let j = afterA;
    if (cmd === 'frac') {
      while (s[j] === ' ') j++;
      if (s[j] !== '{') { s = s.slice(0, at) + '‹frac?›' + s.slice(braceAt); continue; }
      const [B, afterB] = readBrace(s, j);
      const L = convertMath(A), R = convertMath(B);
      const left = needParen(L) ? `(${L})` : L;
      const right = needParen(R) ? `(${R})` : R;
      s = s.slice(0, at) + `${left}/${right}` + s.slice(afterB);
    } else if (cmd === 'sqrt') {
      const n = m[1] ? m[1].slice(1, -1) : null;
      const X = `(${convertMath(A)})`;
      s = s.slice(0, at) + (n ? mapLetters(convertMath(n), SUP) : '') + '√' + X + s.slice(afterA);
    } else if (cmd === 'mathbb') {
      s = s.slice(0, at) + mapLetters(A, BB) + s.slice(afterA);
    } else if (cmd === 'mathcal') {
      s = s.slice(0, at) + mapLetters(A, CAL) + s.slice(afterA);
    } else if (cmd === 'mathbf') {
      s = s.slice(0, at) + mapLetters(A, BF) + s.slice(afterA);
    } else if (cmd === 'mathit') {
      s = s.slice(0, at) + mapLetters(A, IT) + s.slice(afterA);
    } else if (cmd === 'mathsf' || cmd === 'mathrm' || cmd === 'operatorname' || cmd === 'mbox' || cmd === 'text') {
      s = s.slice(0, at) + A + s.slice(afterA);
    } else if (/^(?:bar|overline|hat|tilde|dot|ddot|vec|underline)$/.test(cmd)) {
      const COMB = { bar:'\u0304', overline:'\u0304', underline:'\u0332', hat:'\u0302',
                     tilde:'\u0303', dot:'\u0307', ddot:'\u0308', vec:'\u20D7' };
      s = s.slice(0, at) + convertMath(A) + COMB[cmd] + s.slice(afterA);
    }
  }
  // 命名命令（在上下标之前，这样 ^{\prime} / _{\max} 这类组内容已经是字符）
  s = s.replace(/\\([a-zA-Z]+)/g, (full, name) => {
    if (name in CMD) return CMD[name];
    if (name === 'top') return 'ᵀ';
    if (/^(?:lim|sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|sinh|cosh|tanh|ln|log|lg|exp|max|min|sup|inf|det|dim|ker|rank|tr|sgn|gcd|lcm|mod|deg|arg|span|diag)$/.test(name)) return name;
    return name.length === 1 ? name : full;     // 认不出来的保留原样，便于人工发现
  });
  s = s.replace(/\\\{/g, '\u0001').replace(/\\\}/g, '\u0002');
  s = s.replace(/\\([%&#_$])/g, '$1').replace(/\\[,;:!]/g, (m) => (m === '\\,' ? ' ' : ''));

  // 上下标：先把所有 {...} 组处理完（全局、迭代到稳定），再处理单字符形式
  let g2 = 0;
  while (g2++ < 100) {
    const before = s;
    s = s.replace(/\^\{([^{}]*)\}/g, (_, t) => toSuper(t));
    s = s.replace(/_\{([^{}]*)\}/g, (_, t) => toSub(t));
    if (s === before) break;
  }
  let g3 = 0;
  while (g3++ < 100) {
    const before = s;
    s = s.replace(/\^([A-Za-z0-9+\-])/g, (_, c) => toSuper(c));
    s = s.replace(/_([A-Za-z0-9])/g, (_, c) => toSub(c));
    if (s === before) break;
  }
  // 度数符号 & 减号（印刷体用 U+2212，不用连字符）
  s = s.replace(/\^\{?\\?circ\}?/g, '°').replace(/\^\{?∘\}?/g, '°');
  s = s.replace(/(?<=[A-Za-z0-9)]) *-(?=[A-Za-z0-9(])/g, ' − ');
  s = s.replace(/(?<=[=≤≥→⇒(, ])- *(?=[0-9])/g, '−');
  // 收尾：空格与残留
  s = s.replace(/(→)\s+(?=[A-Za-z0-9(])/g, '$1');
  s = s.replace(/\|\s+(?=[A-Za-z0-9(])/g, '|');
  s = s.replace(/(?<=[A-Za-z0-9)₀₁₂₃₄₅₆₇₈₉])\s*([<>])\s*(?=[A-Za-z0-9(\-−])/g, ' $1 ');
  s = s.replace(/\\(?:left|right|big|Big|bigg|Bigg)\s*\.?/g, '');
  s = s.replace(/\\displaystyle|\\textstyle/g, '');
  s = s.replace(/[{}]/g, '');
  s = s.replace(/[\u0001\u0002]/g, (c) => (c === '\u0001' ? '{' : '}'));
  s = s.replace(/\s{2,}/g, ' ').trim();
  return s;
}

function convert(text) {
  let s = text;
  // 显示/行内公式统一按"去掉分隔符、内部转字符"处理
  s = s.replace(/\$\$([\s\S]*?)\$\$/g, (_, m) => '\n' + convertMath(m) + '\n');
  s = s.replace(/\\\[([\s\S]*?)\\\]/g, (_, m) => '\n' + convertMath(m) + '\n');
  s = s.replace(/\\\(([\s\S]*?)\\\)/g, (_, m) => convertMath(m));
  s = s.replace(/\$([^$\n]+?)\$/g, (_, m) => convertMath(m));
  // 无分隔符的裸 LaTeX（常见于 agent 直接写 \frac{}{} ）
  if (/\\[a-zA-Z]+\s*[{[]/.test(s)) {
    s = s.split('\n').map((line) => (/\\[a-zA-Z]+\s*[{[]/.test(line) ? convertMath(line) : line)).join('\n');
  }
  // ASCII 近似 → 印刷体字符（只处理独立出现、语义明确的）
  s = s.replace(/<=/g, '≤').replace(/>=/g, '≥').replace(/!=/g, '≠')
       .replace(/->/g, '→').replace(/=>/g, '⇒').replace(/\+\/-/g, '±')
       .replace(/\bsqrt\(/g, '√(').replace(/\.\.\./g, '…');
  return s;
}

// ---------- CLI ----------
const argv = process.argv.slice(2);
if (argv.includes('-h') || argv.includes('--help')) {
  console.log(`usage: node bin/latex-to-print.mjs (--text '<含有 LaTeX 的文本>' | <file.md> | -) [-o out.md]\n` +
    `把 LaTeX 转成印刷体 Unicode 文本。stdin 用 - 。`);
  process.exit(0);
}
const ti = argv.indexOf('--text');
const oi = argv.indexOf('-o');
let input;
if (ti >= 0) input = argv[ti + 1] ?? '';
else if (argv[0] && argv[0] !== '-') input = fs.readFileSync(argv[0], 'utf8');
else input = fs.readFileSync(0, 'utf8');

const out = convert(input);
if (oi >= 0) { fs.writeFileSync(argv[oi + 1], out, 'utf8'); console.error('written ' + argv[oi + 1]); }
else process.stdout.write(out + (out.endsWith('\n') ? '' : '\n'));
