#!/usr/bin/env perl
# P1 设计令牌收敛脚本：将 src 内硬编码的色值/圆角/阴影/字号替换为 CSS 令牌
# 用法: perl scripts/codemod-tokens.pl <file...>
use strict;
use warnings;

while (my $file = shift @ARGV) {
  open my $in, '<', $file or die "open $file: $!";
  local $/;
  my $src = <$in>;
  close $in;
  my $orig = $src;

  # ---------- 渐变色（先长串） ----------
  $src =~ s/linear-gradient\(135deg,\s*#ff7a3c,\s*#ff4a1c\)/var(--primary-gradient)/gi;
  $src =~ s/linear-gradient\(135deg,\s*#ff8a45,\s*#ff6427\)/var(--primary-gradient)/gi;
  $src =~ s/linear-gradient\(135deg,\s*#ff8c43,\s*#ff5e24\)/var(--primary-gradient)/gi;
  $src =~ s/linear-gradient\(135deg,\s*#ff6b5f,\s*#e53935\)/var(--danger-gradient)/gi;

  # ---------- 主色系 ----------
  $src =~ s/(?<![0-9a-f])#ff5a2c(?![0-9a-f])/var(--primary)/gi;
  $src =~ s/(?<![0-9a-f])#f05a2a(?![0-9a-f])/var(--primary-hover)/gi;
  $src =~ s/(?<![0-9a-f])#d43a1a(?![0-9a-f])/var(--primary-active)/gi;
  $src =~ s/(?<![0-9a-f])#ff6427(?![0-9a-f])/var(--primary)/gi;
  $src =~ s/(?<![0-9a-f])#ff6d2d(?![0-9a-f])/var(--primary)/gi;
  $src =~ s/(?<![0-9a-f])#ec6331(?![0-9a-f])/var(--primary)/gi;
  $src =~ s/(?<![0-9a-f])#e65b2d(?![0-9a-f])/var(--primary)/gi;
  $src =~ s/(?<![0-9a-f])#e75b29(?![0-9a-f])/var(--primary)/gi;

  # ---------- 危险红 ----------
  $src =~ s/(?<![0-9a-f])#e53935(?![0-9a-f])/var(--danger)/gi;
  $src =~ s/(?<![0-9a-f])#c0392b(?![0-9a-f])/var(--danger-active)/gi;
  $src =~ s/(?<![0-9a-f])#b03a2e(?![0-9a-f])/var(--danger-active)/gi;
  $src =~ s/(?<![0-9a-f])#e33(?![0-9a-f])/var(--danger)/gi;
  $src =~ s/(?<![0-9a-f])#d33(?![0-9a-f])/var(--danger)/gi;
  $src =~ s/(?<![0-9a-f])#c33(?![0-9a-f])/var(--danger)/gi;
  $src =~ s/(?<![0-9a-f])#fff0f0(?![0-9a-f])/var(--danger-light)/gi;
  $src =~ s/(?<![0-9a-f])#fdeceb(?![0-9a-f])/var(--danger-light)/gi;
  $src =~ s/(?<![0-9a-f])#ffd0cc(?![0-9a-f])/var(--danger-border)/gi;

  # ---------- 信息蓝 ----------
  $src =~ s/(?<![0-9a-f])#4776c8(?![0-9a-f])/var(--info)/gi;
  $src =~ s/(?<![0-9a-f])#3373a8(?![0-9a-f])/var(--info)/gi;
  $src =~ s/(?<![0-9a-f])#eef3ff(?![0-9a-f])/var(--info-light)/gi;
  $src =~ s/(?<![0-9a-f])#eef7ff(?![0-9a-f])/var(--info-light)/gi;

  # ---------- 警示黄 ----------
  $src =~ s/(?<![0-9a-f])#a66b00(?![0-9a-f])/var(--warning)/gi;
  $src =~ s/(?<![0-9a-f])#fff8df(?![0-9a-f])/var(--warning-light)/gi;

  # ---------- 中性色 ----------
  $src =~ s/(?<![0-9a-f])#777(?![0-9a-f])/var(--text-secondary)/gi;
  $src =~ s/(?<![0-9a-f])#888(?![0-9a-f])/var(--text-secondary)/gi;
  $src =~ s/(?<![0-9a-f])#555(?![0-9a-f])/var(--text-regular)/gi;
  $src =~ s/(?<![0-9a-f])#fafafa(?![0-9a-f])/var(--surface-muted)/gi;
  $src =~ s/(?<![0-9a-f])#f2f2f2(?![0-9a-f])/var(--surface-muted)/gi;
  $src =~ s/(?<![0-9a-f])#f5f5f5(?![0-9a-f])/var(--surface-muted)/gi;
  $src =~ s/(?<![0-9a-f])#f5f5f6(?![0-9a-f])/var(--surface-muted)/gi;

  # ---------- 圆角五档收敛 ----------
  $src =~ s/border-radius:\s*(?:2|3|4|5)px/border-radius: var(--radius-xs)/g;
  $src =~ s/border-radius:\s*(?:6|7|8|9|10)px/border-radius: var(--radius-sm)/g;
  $src =~ s/border-radius:\s*(?:11|12|13)px/border-radius: var(--radius-md)/g;
  $src =~ s/border-radius:\s*(?:14|15|16)px/border-radius: var(--radius-lg)/g;
  $src =~ s/border-radius:\s*(?:17|18|19|20|21|22)px/border-radius: var(--radius-pill)/g;

  # ---------- 阴影三档收敛 ----------
  $src =~ s/0 20px 60px rgba\(0,\s*0,\s*0,\s*0\.25\)/var(--shadow-modal)/g;
  $src =~ s/0 24px 70px rgba\(0,\s*0,\s*0,\s*0\.24\)/var(--shadow-modal)/g;
  $src =~ s/0 26px 80px rgba\(0,\s*0,\s*0,\s*0\.3\)/var(--shadow-modal)/g;
  $src =~ s/0 28px 80px rgba\(0,\s*0,\s*0,\s*0\.28\)/var(--shadow-modal)/g;
  $src =~ s/0 18px 45px rgba\(52,\s*37,\s*26,\s*0\.16\)/var(--shadow-dropdown)/g;
  $src =~ s/0 1px 3px rgba\(0,\s*0,\s*0,\s*0\.03\)/var(--shadow-card)/g;

  # ---------- 字号（仅等值替换，零视觉差异） ----------
  $src =~ s/font-size:\s*12px/font-size: var(--font-sm)/g;
  $src =~ s/font-size:\s*14px/font-size: var(--font-md)/g;
  $src =~ s/font-size:\s*17px/font-size: var(--font-lg)/g;

  next if $src eq $orig;
  open my $out, '>', $file or die "write $file: $!";
  print $out $src;
  close $out;
  print "updated: $file\n";
}
