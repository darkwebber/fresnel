class Fresnel < Formula
  include Language::Python::Virtualenv

  desc "Mac-native orchestration harness for bounded local coding agents"
  homepage "https://github.com/darkwebber/fresnel"
  url "https://github.com/darkwebber/fresnel/releases/download/v0.1.2/fresnel_agent-0.1.2.tar.gz"
  sha256 "b8f9a5bf972ba174ddf4c86be61830245919394cb4268c6fe20da25d8c6877ae"
  license "Apache-2.0"

  depends_on arch: :arm64
  depends_on "python@3.13"
  depends_on "uv"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "Fresnel 0.1.2", shell_output("#{bin}/fresnel --version")
  end
end
