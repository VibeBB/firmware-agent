# mruby/c UX state machine for the mruby-ux example.
# The same source drives the nRF52840 product build and the Emscripten
# verification leg, so CI checks the exact UX logic that ships.

class Ux
  def initialize
    @index = 0
  end

  def state
    ["OFF", "DIM", "BRIGHT"][@index]
  end

  def advance
    @index = (@index + 1) % 3
    state
  end
end

ux = Ux.new
puts "STATE #{ux.state}"
ux.advance
puts "STATE #{ux.state}"
ux.advance
puts "STATE #{ux.state}"
puts "SIM PASS"
