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
  depends_on "glow"
  depends_on "darkwebber/tap/termtex"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "Fresnel {version}", shell_output("#{{bin}}/fresnel --version")
  end
end
'''


def termtex_formula() -> str:
    """Return the reviewed, commit-pinned math renderer formula used by Fresnel."""
    return '''class Termtex < Formula
  desc "Render LaTeX math as Unicode or ASCII in a terminal"
  homepage "https://github.com/doug/termtex"
  url "https://github.com/doug/termtex/archive/e3e21f41b38e9c2f579752dcfd9e23ac4cd15df7.tar.gz"
  version "0.0.0-e3e21f4"
  sha256 "1503d47bf6150312af96396e1f3036e0b6aa479a7d7961c71e9caeadbdeafe33"
  license "Apache-2.0"

  depends_on "go" => :build

  def install
    system "go", "build", *std_go_args(output: bin/"termtex"), "./cmd/termtex"
  end

  test do
    output = pipe_output("#{bin}/termtex -ascii", "$x^2$")
    assert_match "2", output
  end
end
'''
