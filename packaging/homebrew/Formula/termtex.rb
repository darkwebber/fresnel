class Termtex < Formula
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
