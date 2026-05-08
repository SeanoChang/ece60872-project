import re

with open('docs/paper/report.tex', 'r') as f:
    content = f.read()

# 1. Swap Related Work and Background
background_threat_start = content.find('\\section{Background and Problem Formulation}\\label{sec:threat}')
related_work_start = content.find('\\section{Related Work}\\label{sec:related}')
background_coverage_start = content.find('\\section{Background: Coverage Framing}')
our_design_start = content.find('%======================================================================\n\\section{Our Design}\\label{sec:method}')

part1 = content[:background_threat_start]
background_threat_text = content[background_threat_start:related_work_start]
related_work_text = content[related_work_start:background_coverage_start]
background_coverage_text = content[background_coverage_start:our_design_start]
part_rest = content[our_design_start:]

# Modify background headers
background_threat_text = background_threat_text.replace(
    '\\section{Background and Problem Formulation}\\label{sec:threat}\n\n\\subsection{Threat Model}',
    '\\section{Background}\\label{sec:background}\n\n\\subsection{Threat Model and Problem Formulation}\\label{sec:threat}'
)
background_coverage_text = background_coverage_text.replace(
    '\\section{Background: Coverage Framing}',
    '\\subsection{Coverage Framing}'
)

new_content = part1 + related_work_text + background_threat_text + background_coverage_text + part_rest

# 2. Merge Cost and Latency Analysis into Evaluation
cost_start = new_content.find('%======================================================================\n\\section{Cost and Latency Analysis}\\label{sec:cost}')
discussion_start = new_content.find('%======================================================================\n\\section{Discussion}\\label{sec:discussion}')

if cost_start != -1 and discussion_start != -1:
    cost_text = new_content[cost_start:discussion_start]
    # Remove the %=== separator and change to subsection
    cost_text = cost_text.replace('%======================================================================\n', '')
    cost_text = cost_text.replace('\\section{Cost and Latency Analysis}', '\\subsection{Cost and Latency Analysis}')
    
    new_content = new_content[:cost_start] + cost_text + new_content[discussion_start:]

# 3. Merge Discussion and Conclusion
discussion_start = new_content.find('\\section{Discussion}\\label{sec:discussion}')
conclusion_start = new_content.find('%======================================================================\n\\section{Conclusion}\\label{sec:conclusion}')
appendix_start = new_content.find('%======================================================================\n\\bibliographystyle{plain}')

if discussion_start != -1 and conclusion_start != -1:
    new_content = new_content.replace('\\section{Discussion}\\label{sec:discussion}', '\\section{Discussion and Conclusion}\\label{sec:discussion}')
    
    conclusion_text = new_content[conclusion_start:appendix_start]
    conclusion_text = conclusion_text.replace('%======================================================================\n\\section{Conclusion}\\label{sec:conclusion}', '\\subsection{Conclusion}\\label{sec:conclusion}')
    
    new_content = new_content[:conclusion_start] + conclusion_text + new_content[appendix_start:]

with open('docs/paper/report.tex', 'w') as f:
    f.write(new_content)

