import {ComponentPreview, Previews} from '@react-buddy/ide-toolbox'
import {PaletteTree} from './palette'
import App from "../App.jsx";
import InputBar from "../components/InputBar.jsx";
import MarkdownRenderer from "../components/MarkdownRenderer.jsx";
import MessageList from "../components/MessageList.jsx";
import ProviderSelector from "../components/ProviderSelector.jsx";
import SubagentCard from "../components/SubagentCard.jsx";
import ThreadHistory from "../components/ThreadHistory.jsx";
import TodoList from "../components/TodoList.jsx";
import ToolCallRow from "../components/ToolCallRow.jsx";

const ComponentPreviews = () => {
    return (
        <Previews palette={<PaletteTree/>}>
            <ComponentPreview path="/App">
                <App/>
            </ComponentPreview>
            <ComponentPreview path="/InputBar">
                <InputBar/>
            </ComponentPreview>
            <ComponentPreview path="/MarkdownRenderer">
                <MarkdownRenderer/>
            </ComponentPreview>
            <ComponentPreview path="/MessageList">
                <MessageList/>
            </ComponentPreview>
            <ComponentPreview path="/ProviderSelector">
                <ProviderSelector/>
            </ComponentPreview>
            <ComponentPreview path="/SubagentCard">
                <SubagentCard/>
            </ComponentPreview>
            <ComponentPreview path="/ThreadHistory">
                <ThreadHistory/>
            </ComponentPreview>
            <ComponentPreview path="/TodoList">
                <TodoList/>
            </ComponentPreview>
            <ComponentPreview path="/ToolCallRow">
                <ToolCallRow/>
            </ComponentPreview>
            <ComponentPreview path="/PaletteTree">
                <PaletteTree/>
            </ComponentPreview>
        </Previews>
    )
}

export default ComponentPreviews
