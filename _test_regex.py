import re
from services.leidsa_history import fetch_page

h = fetch_page("https://www.leidsa.com/results/Leidsa/Loto/1_2061", False)["html"]
i = h.find('drawResults\\":[{')
s = h[i : i + 3000]
print(s[:2500])

# count drawnValues pattern variants
for pat in [
    r'drawnValues\\":\[\{\\"drawnValues\\":\[',
    r'\\"drawnValues\\":\[\{\\"drawnValues\\":\[',
    r'drawnValues":\[{"drawnValues":\[',
]:
    print(pat, len(re.findall(pat, h[i : i + 500000])))
