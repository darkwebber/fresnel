"""Deterministic Homebrew formula generation for published release archives."""

from __future__ import annotations


def homebrew_formula(
    version: str,
    url: str,
    sha256: str,
    homepage: str = "https://github.com/fresnel-ai/fresnel",
) -> str:
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256.lower()):
        raise ValueError("sha256 must contain 64 hexadecimal characters")
    return f'''class Fresnel < Formula
  include Language::Python::Virtualenv

  desc "Mac-native orchestration harness for bounded local coding agents"
  homepage "{homepage}"
  url "{url}"
  sha256 "{sha256}"
  license "Apache-2.0"

  depends_on arch: :arm64
  depends_on "python@3.13"
  depends_on "uv"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "Fresnel {version}", shell_output("#{{bin}}/fresnel --version")
  end
end
'''
