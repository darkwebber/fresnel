class Fresnel < Formula
  include Language::Python::Virtualenv

  desc "Mac-native orchestration harness for bounded local coding agents"
  homepage "https://github.com/darkwebber/fresnel"
  url "https://github.com/darkwebber/fresnel/releases/download/v0.1.1/fresnel_agent-0.1.1.tar.gz"
  sha256 "1d23415c80d71793e5a55a4fd91d06aafcbf336e2ffd6af2c2982d5e6afad023"
  license "Apache-2.0"

  depends_on arch: :arm64
  depends_on "python@3.13"
  depends_on "uv"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "Fresnel 0.1.1", shell_output("#{bin}/fresnel --version")
  end
end
