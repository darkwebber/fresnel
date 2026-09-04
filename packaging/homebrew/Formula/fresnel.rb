class Fresnel < Formula
  include Language::Python::Virtualenv

  desc "Mac-native orchestration harness for bounded local coding agents"
  homepage "https://github.com/darkwebber/fresnel"
  url "https://github.com/darkwebber/fresnel/releases/download/v0.1.0/fresnel_agent-0.1.0.tar.gz"
  sha256 "ffbff7bb36a972be82cdeeaebfdbf176de2c30f705ae5a7867332e2a9a8cb0e2"
  license "Apache-2.0"

  depends_on arch: :arm64
  depends_on "python@3.13"
  depends_on "uv"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "Fresnel 0.1.0", shell_output("#{bin}/fresnel --version")
  end
end
