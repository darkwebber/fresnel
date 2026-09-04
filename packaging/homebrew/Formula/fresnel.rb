class Fresnel < Formula
  include Language::Python::Virtualenv

  desc "Mac-native orchestration harness for bounded local coding agents"
  homepage "https://github.com/darkwebber/fresnel"
  url "https://github.com/darkwebber/fresnel/releases/download/v0.4.0/fresnel_agent-0.4.0.tar.gz"
  sha256 "78c56b2f408404a5277cef620d9c1054f6922b19bd70ba1a872647adf0c5df7d"
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
    assert_match "Fresnel 0.4.0", shell_output("#{bin}/fresnel --version")
  end
end
