<#
 Generates a synthetic evaluation set of listing screenshots with KNOWN prices (99, 129, 999, 1299,
 1999, 12999 in several formats: "Rs." / rupee symbol / plain, with and without thousands commas,
 and decimals), each with a strikethrough MRP and a "NN% off" line, plus manifest.json for
 run_eval.py. Synthetic on purpose: it isolates digit-reading from layout noise. It is NOT a
 substitute for real seller screenshots (spec Q7/Q18 needs those).

 Usage:  .\make_images.ps1 -W 1280 -OutDir .\eval_images      # writes .\eval_images\w1280\
#>
param([int]$W = 1280, [string]$OutDir = ".\eval_images")
Add-Type -AssemblyName System.Drawing
$out = Join-Path $OutDir "w$W"
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Force $out | Out-Null
$rupee = [string][char]0x20B9
function Fmt([decimal]$v, [string]$style) {
  $n = [int][math]::Floor($v)
  $commas = $n.ToString('N0', [System.Globalization.CultureInfo]::InvariantCulture)
  switch ($style) {
    'symbol_comma' { return "$rupee$commas" }
    'rs_comma'     { return "Rs. $commas" }
    'plain'        { return "$n" }
    'symbol_plain' { return "$rupee$n" }
    'decimal'      { return ("$rupee{0}.00" -f $commas) }
  }
}
$cases = @()
foreach ($p in 99, 129, 999, 1299, 1999, 12999) { foreach ($s in 'symbol_comma', 'rs_comma', 'plain') { $cases += ,@($p, $s) } }
$cases += ,@(1299, 'symbol_plain'); $cases += ,@(12999, 'symbol_plain'); $cases += ,@(1299, 'decimal'); $cases += ,@(999, 'decimal')
$manifest = @()
$i = 0
foreach ($c in $cases) {
  $price = [decimal]$c[0]; $style = $c[1]
  $mrp = [math]::Round($price * 1.5 / 10) * 10; if ($mrp -le $price) { $mrp = $price + 50 }
  $pct = [int][math]::Round(100 * ($mrp - $price) / $mrp)
  $w = $W; $h = [int]($W * 0.625); $sc = $W / 1280.0
  $bmp = New-Object System.Drawing.Bitmap $w, $h
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = 'AntiAlias'; $g.TextRenderingHint = 'AntiAlias'
  $g.Clear([System.Drawing.Color]::White)
  $title = New-Object System.Drawing.Font('Segoe UI', [single](30*$sc), [System.Drawing.FontStyle]::Bold)
  $big = New-Object System.Drawing.Font('Segoe UI', [single](54*$sc), [System.Drawing.FontStyle]::Bold)
  $mid = New-Object System.Drawing.Font('Segoe UI', [single](26*$sc))
  $strike = New-Object System.Drawing.Font('Segoe UI', [single](26*$sc), [System.Drawing.FontStyle]::Strikeout)
  $names = 'Cotton Floral Kurti for Women', 'Wireless Bluetooth Earbuds with Mic', 'Stainless Steel Water Bottle 1L', 'Men Running Shoes Lightweight'
  $name = $names[$i % 4]
  $g.DrawString("$name - Pack of 2", $title, [System.Drawing.Brushes]::Black, [single](60*$sc), [single](50*$sc))
  $g.DrawString((Fmt $price $style), $big, [System.Drawing.Brushes]::DarkRed, [single](60*$sc), [single](140*$sc))
  $g.DrawString(("M.R.P.: " + (Fmt $mrp $style)), $strike, [System.Drawing.Brushes]::Gray, [single](60*$sc), [single](240*$sc))
  $g.DrawString("$pct% off", $mid, [System.Drawing.Brushes]::DarkGreen, [single](60*$sc), [single](310*$sc))
  $g.DrawString('In stock', $mid, [System.Drawing.Brushes]::DarkGreen, [single](60*$sc), [single](380*$sc))
  $g.DrawString('Free delivery by Tuesday. Sold by StyleHub Retail.', $mid, [System.Drawing.Brushes]::Black, [single](60*$sc), [single](450*$sc))
  $g.Dispose()
  $file = ("eval_{0:D2}.png" -f $i)
  $bmp.Save("$out\$file", [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
  $manifest += [pscustomobject]@{ file = $file; style = $style; expected_price_rupees = [int]$price; expected_mrp_rupees = [int]$mrp; rendered_price = (Fmt $price $style) }
  $i++
}
$manifest | ConvertTo-Json | Out-File -Encoding utf8 "$out\manifest.json"
"$i images written to $out"
