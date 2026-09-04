class Fresnel < Formula
  include Language::Python::Virtualenv

  desc "Mac-native orchestration harness for bounded local coding agents"
  homepage "https://github.com/darkwebber/fresnel"
  url "https://github.com/darkwebber/fresnel/releases/download/v0.4.1/fresnel_agent-0.4.1.tar.gz"
  sha256 "fa883a73265b0ebdc62a208c6f53635dfce9e70d9e2c17c8631e8fec8701ca91"
  license "Apache-2.0"

  depends_on arch: :arm64
  depends_on "darkwebber/tap/termtex"
  depends_on "glow"
  depends_on "python@3.13"
  depends_on "uv"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "Fresnel 0.4.1", shell_output("#{bin}/fresnel --version")
  end
end
