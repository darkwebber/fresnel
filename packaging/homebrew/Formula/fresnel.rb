class Fresnel < Formula
  include Language::Python::Virtualenv

  desc "Mac-native orchestration harness for bounded local coding agents"
  homepage "https://github.com/darkwebber/fresnel"
  url "https://github.com/darkwebber/fresnel/releases/download/v0.5.1/fresnel_agent-0.5.1.tar.gz"
  sha256 "092ff0d8d2e6c1ef45790255ca706a8ec8e1f5816e8c3762f05d3163d4590d05"
  license "Apache-2.0"

  depends_on arch: :arm64
  depends_on "darkwebber/tap/termtex"
  depends_on "glow"
  depends_on "python@3.13"

  def install
    system "/usr/bin/swiftc", "-O", "-target", "arm64-apple-macosx14.0",
           buildpath/"native/FresnelUI.swift", "-o", buildpath/"fresnel-ui"
    system "/usr/bin/swiftc", "-O", "-target", "arm64-apple-macosx14.0",
           buildpath/"native/FresnelSupervisor.swift", "-o", buildpath/"fresnel-supervisor"
    system "/usr/bin/codesign", "--force", "--sign", "-", buildpath/"fresnel-ui"
    system "/usr/bin/codesign", "--force", "--sign", "-", buildpath/"fresnel-supervisor"
    virtualenv_install_with_resources
    bin.install buildpath/"fresnel-ui", buildpath/"fresnel-supervisor"
  end

  test do
    assert_match "Fresnel 0.5.1", shell_output("#{bin}/fresnel --version")
    dashboard_input = <<~JSON
      {"healthy":true,"worker":"idle","chip":"Apple Silicon","memory_free_percent":50,
       "profile":"balanced","personalization":false,"runs":[]}
    JSON
    dashboard = pipe_output("#{bin}/fresnel-ui dashboard", dashboard_input)
    assert_match "FRESNEL", dashboard
    assert_match '"ok":true', shell_output("#{bin}/fresnel-supervisor --self-test")
  end
end
