import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './markdown.css';

export default function CoachMarkdown({text}: {text: string}) {
  return <div className="coach-markdown"><Markdown remarkPlugins={[remarkGfm]} skipHtml
    components={{a: ({children, href}) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
      img: ({alt}) => <span>{alt}</span>}}>{text}</Markdown></div>;
}
