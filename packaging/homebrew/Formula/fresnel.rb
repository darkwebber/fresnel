class Fresnel < Formula
  include Language::Python::Virtualenv

  desc "Mac-native orchestration harness for bounded local coding agents"
  homepage "https://github.com/darkwebber/fresnel"
  url "https://github.com/darkwebber/fresnel/releases/download/v0.2.0/fresnel_agent-0.2.0.tar.gz"
  sha256 "bd5ecf7693f87892fbf6db071e743df7edf1978e50fcae2dcfc6e92e948eb804"
  license "Apache-2.0"

  depends_on arch: :arm64
  depends_on "python@3.13"
  depends_on "uv"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "Fresnel 0.2.0", shell_output("#{bin}/fresnel --version")
  end
end
